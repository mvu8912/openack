package OpenAck::Admin;

use strict;
use warnings;

use Dancer2;
use YAML::XS qw(LoadFile DumpFile);
use JSON::MaybeXS qw(decode_json);
use File::Path qw(make_path);
use File::Copy qw(move);
use File::Basename qw(basename);
use File::Spec;
use Path::Tiny;
use UUID::Tiny ':std';
use POSIX qw(strftime);
use Archive::Zip qw(:ERROR_CODES :CONSTANTS);
use HTTP::Request::Common qw(POST);
use LWP::UserAgent;

set session => 'Simple';
set template => 'template_toolkit';

my $MESSAGES_ROOT = path($ENV{OPENACK_MESSAGES_ROOT} // '/messages');
my $PEOPLE_FILE = path($ENV{OPENACK_PEOPLE_FILE} // '/var/lib/openack/people.yml');
my $LOG_PATH = path($ENV{OPENACK_LOG_PATH} // File::Spec->catfile(path('.')->absolute, 'transactions.log'));
my $OPENACK_API = $ENV{OPENACK_API} // 'http://127.0.0.1:8080';

sub _admin_password { return $ENV{OPENACK_ADMIN_PASS} // 'password' }

sub _require_auth {
    return 1 if session('user') && session('user') eq 'admin';
    redirect '/login';
    return;
}

sub _load_people {
    die "People file not found: $PEOPLE_FILE" unless -f $PEOPLE_FILE;
    my $yaml = LoadFile($PEOPLE_FILE->stringify) || {};
    my $raw = ref($yaml) eq 'HASH' ? ($yaml->{people} || []) : [];
    my %seen;
    my @people = grep { !$seen{$_}++ } map { lc($_ =~ s/^\s+|\s+$//gr) } grep { defined && /\S/ } @$raw;
    die "No valid people in $PEOPLE_FILE" unless @people;
    return \@people;
}

sub _save_people {
    my ($people) = @_;
    DumpFile($PEOPLE_FILE->stringify, { people => $people });
}

sub _parse_message_file {
    my ($file) = @_;
    my $text = path($file)->slurp_utf8;
    my ($header) = $text =~ /=== HEADER ===\n(.*?)\n\n/s;
    my %meta;
    if ($header) {
        for my $line (split /\n/, $header) {
            my ($k, $v) = split /:\s*/, $line, 2;
            $meta{$k} = $v if defined $k && defined $v;
        }
    }
    my ($body) = $text =~ /=== HEADER ===\n.*?\n\n(.*?)\n=== FOOTER ===/s;
    $body //= '';
    my @attachments;
    if ($text =~ /=== FOOTER ===\nattachments:\n(.*)$/s) {
        @attachments = map { s/^-\s*//r } grep { /^-/ } split /\n/, $1;
    }
    return {
        message_id => basename($file),
        file_path => "$file",
        sent_at => ($meta{sent_at} // ''),
        sender => ($meta{from} // ''),
        recipient => ($meta{to} // ''),
        body => $body,
        preview => substr($body, 0, 140),
        attachments => \@attachments,
        is_new => ($file =~ m{/inbox/} ? 1 : 0),
    };
}

sub _list_messages {
    my @records;
    return [] unless -d $MESSAGES_ROOT;
    for my $recipient_dir ($MESSAGES_ROOT->children(qr/.+/)) {
        next unless -d $recipient_dir;
        my $inbox = $recipient_dir->child('inbox');
        if (-d $inbox) {
            for my $file (sort { "$b" cmp "$a" } $inbox->children(qr/\.md$/)) {
                push @records, _parse_message_file($file);
            }
        }
        my $done = $recipient_dir->child('done');
        if (-d $done) {
            for my $zip (sort { "$b" cmp "$a" } $done->children(qr/\.zip$/)) {
                push @records, {
                    message_id => basename($zip),
                    file_path => "$zip",
                    sent_at => basename($zip),
                    sender => '-',
                    recipient => $recipient_dir->basename,
                    body => '(archived)',
                    preview => 'Archived message',
                    attachments => [],
                    is_new => 0,
                };
            }
        }
    }
    return \@records;
}

sub _send_message {
    my ($from, $to, $message, $uploads) = @_;
    my $url = "$OPENACK_API/messages";
    my @content = (
        from => $from,
        to => $to,
        message => $message,
    );

    for my $upload (@$uploads) {
        next unless $upload;
        push @content, files => [
            $upload->tempname,
            $upload->filename,
            Content_Type => $upload->type || 'application/octet-stream',
        ];
    }

    my $ua = LWP::UserAgent->new(timeout => 20);
    my $req = POST($url, Content_Type => 'form-data', Content => \@content);
    my $res = $ua->request($req);
    die "Message send failed: " . $res->status_line unless $res->is_success;
    return decode_json($res->decoded_content);
}

sub _archive_inbox_message {
    my ($message_path) = @_;
    return unless -f $message_path;
    my $details = _parse_message_file($message_path);
    my $recipient = $details->{recipient} || path($message_path)->parent->parent->basename;

    my $done_dir = path($MESSAGES_ROOT, $recipient, 'done');
    make_path($done_dir->stringify);

    my $uuid = create_uuid_as_string(UUID_V4);
    my $stamp = strftime('%Y-%m-%dT%H:%M:%SZ', gmtime);
    my $zip_path = $done_dir->child("$stamp-$uuid.zip");

    my $zip = Archive::Zip->new();
    $zip->addFile($message_path, basename($message_path));
    for my $attachment (@{$details->{attachments}}) {
        next unless -f $attachment;
        $zip->addFile($attachment, basename($attachment));
    }
    $zip->writeToFileNamed($zip_path->stringify) == AZ_OK or die 'Unable to write archive';

    unlink $message_path;
    for my $attachment (@{$details->{attachments}}) {
        unlink $attachment if -f $attachment;
    }
}

get '/' => sub {
    _require_auth() or return;
    redirect '/dashboard';
};

get '/login' => sub {
    template 'login' => { error => undef };
};

post '/login' => sub {
    my $username = body_parameters->get('username') // '';
    my $password = body_parameters->get('password') // '';

    if ($username eq 'admin' && $password eq _admin_password()) {
        session user => 'admin';
        redirect '/dashboard';
    }

    status 401;
    template 'login' => { error => 'Invalid credentials' };
};

get '/logout' => sub {
    app->destroy_session;
    redirect '/login';
};

get '/dashboard' => sub {
    _require_auth() or return;
    my $messages = _list_messages();
    my $people = _load_people();
    template 'dashboard' => {
        messages => $messages,
        people => $people,
    };
};

post '/messages/send' => sub {
    _require_auth() or return;

    my $from = body_parameters->get('from') // '';
    my $to = body_parameters->get('to') // '';
    my $message = body_parameters->get('message') // '';
    my @uploads = upload('files');

    eval { _send_message($from, $to, $message, \@uploads); 1 }
      or do {
          my $error = $@ || 'Unknown error';
          status 500;
          return to_json({ ok => 0, error => "$error" });
      };

    return to_json({ ok => 1 });
};

post '/messages/archive' => sub {
    _require_auth() or return;
    my $path = body_parameters->get('path') // '';
    eval { _archive_inbox_message($path); 1 }
      or do {
          status 500;
          return to_json({ ok => 0, error => "$@" });
      };
    return to_json({ ok => 1 });
};

post '/messages/delete' => sub {
    _require_auth() or return;
    my $path = body_parameters->get('path') // '';
    if ($path && -f $path) {
        unlink $path;
    }
    return to_json({ ok => 1 });
};

post '/people/add' => sub {
    _require_auth() or return;
    my $new_person = lc(body_parameters->get('name') // '');
    $new_person =~ s/^\s+|\s+$//g;
    my $people = _load_people();
    if ($new_person =~ /^[a-z0-9_-]+$/ && !(grep { $_ eq $new_person } @$people)) {
        push @$people, $new_person;
        @$people = sort @$people;
        _save_people($people);
    }
    redirect '/dashboard';
};

post '/people/remove' => sub {
    _require_auth() or return;
    my $name = lc(body_parameters->get('name') // '');
    my $people = _load_people();
    my @kept = grep { $_ ne $name } @$people;
    _save_people(\@kept) if @kept;
    redirect '/dashboard';
};

true;
