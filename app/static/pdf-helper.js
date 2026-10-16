// Render PDF pages one at a time so large chapters do not keep 1000 PNG blobs in memory.
window.renderPdfPages = async function(file, onProgress, onPage) {
  if (!window.pdfjsLib) throw new Error('تعذر تحميل قارئ PDF. جرّب تحديث الصفحة.');
  const bytes = await file.arrayBuffer();
  const pdf = await window.pdfjsLib.getDocument({data: bytes}).promise;
  if (pdf.numPages > 1000) throw new Error('الحد الأقصى 1000 صفحة في الملف الواحد.');
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const baseViewport = page.getViewport({scale: 1});
    const viewport = page.getViewport({scale: Math.min(2, 1800 / baseViewport.width)});
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);
    await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
    const blob = await new Promise((resolve, reject) => {
      canvas.toBlob(result => result ? resolve(result) : reject(new Error('تعذر تحويل الصفحة ' + i + ' إلى صورة.')), 'image/png');
    });
    if (onProgress) onProgress(i, pdf.numPages);
    if (onPage) await onPage({pageNumber: i, blob, width: canvas.width, height: canvas.height});
    canvas.width = 1; canvas.height = 1;
    page.cleanup();
  }
  await pdf.destroy();
  return true;
};