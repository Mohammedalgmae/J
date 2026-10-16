// PDF.js is loaded from a CDN in index.html. This helper renders PDF pages to PNG blobs for the existing image OCR pipeline.
window.renderPdfPages = async function(file, onProgress) {
  if (!window.pdfjsLib) throw new Error('تعذر تحميل قارئ PDF. جرّب تحديث الصفحة.');
  const bytes = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({data: bytes}).promise;
  if (pdf.numPages > 30) throw new Error('الحد الأقصى 30 صفحة في الملف الواحد حاليًا.');
  const pages = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const viewport = page.getViewport({scale: Math.min(2, 1800 / page.getViewport({scale:1}).width)});
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
    await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    pages.push({pageNumber:i, blob, width:canvas.width, height:canvas.height});
    if (onProgress) onProgress(i, pdf.numPages);
    page.cleanup();
  }
  return pages;
};