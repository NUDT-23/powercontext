const lightbox = document.getElementById("lightbox");
const lightboxImg = document.getElementById("lightbox-img");
const lightboxTitle = document.getElementById("lightbox-title");
const lightboxClose = document.getElementById("lightbox-close");

document.querySelectorAll(".shot-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const src = btn.dataset.full;
    if (!src) return;
    lightboxImg.src = src;
    lightboxImg.alt = btn.querySelector("img")?.alt || "";
    lightboxTitle.textContent = btn.dataset.title || "";
    lightbox.showModal();
  });
});

lightboxClose.addEventListener("click", () => lightbox.close());

lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) lightbox.close();
});

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const revealItems = document.querySelectorAll(".reveal");

if (reduceMotion || !("IntersectionObserver" in window)) {
  revealItems.forEach((el) => el.classList.add("is-visible"));
} else {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px" }
  );
  revealItems.forEach((el) => observer.observe(el));
}

document.getElementById("year").textContent = new Date().getFullYear();
