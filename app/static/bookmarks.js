document.addEventListener('click', function (e) {
  const btn = e.target.closest('.star-btn');
  if (!btn) return;
  e.preventDefault();
  const qid = btn.dataset.questionId;
  const fd = new FormData();
  fd.append('question_id', qid);
  fetch('/bookmarks/toggle', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      btn.classList.toggle('is-active', !!data.bookmarked);
      btn.setAttribute('aria-pressed', data.bookmarked ? 'true' : 'false');
    });
});
