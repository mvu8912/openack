document.querySelectorAll('button.action').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const endpoint = btn.dataset.endpoint;
    const path = btn.dataset.path;
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ path }),
    });
    if (res.ok) window.location.reload();
  });
});

document.getElementById('send-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const data = new FormData(form);
  const res = await fetch(form.action, { method: 'POST', body: data });
  if (res.ok) {
    form.reset();
    window.location.reload();
  } else {
    alert('Failed to send message');
  }
});
