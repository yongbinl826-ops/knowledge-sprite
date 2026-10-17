// Audited synthetic fixture only. No third-party or real-site code is executed.
const scenario = new URL(location.href).searchParams.get('scenario') || 'course';
if (scenario === 'course') {
  const schema = document.createElement('script');
  schema.type = 'application/ld+json';
  schema.textContent = JSON.stringify({ '@type': 'Course', name: 'Synthetic Python lists course', description: 'Learn Python lists through two offline fixture lessons.' });
  document.head.append(schema);
  const outline = document.createElement('ol');
  outline.className = 'course-outline';
  for (const [label, path] of [['Lists', '/lesson/lists'], ['Iteration', '/lesson/iteration']]) {
    const item = document.createElement('li');
    const link = document.createElement('a');
    link.textContent = label; link.href = path; item.append(link); outline.append(item);
  }
  document.querySelector('#content').append(outline);
  window.__fixtureDone = true;
} else if (scenario === 'missing') {
  fetch('/not-preapproved.json').catch(() => {});
} else if (scenario === 'post') {
  fetch('/course.js', { method: 'POST', body: 'synthetic' }).catch(() => {});
} else if (scenario === 'navigate') {
  location.href = 'https://elsewhere.example.org/forbidden';
} else if (scenario === 'guard') {
  for (const run of [() => new Worker('/course.js'), () => new WebSocket('wss://renderer.example.org/socket'), () => window.open('/popup'), () => new RTCPeerConnection()]) {
    try { run(); } catch { /* Expected guard failures in audited code. */ }
  }
  window.__fixtureDone = true;
} else if (scenario === 'frame') {
  document.body.append(document.createElement('iframe'));
} else if (scenario === 'wait') {
  // No busy loop: allows a deterministic external deadline/cancel test.
  window.__fixtureDone = false;
}
