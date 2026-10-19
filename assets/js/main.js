(function () {
  "use strict";
  var root = document.documentElement;
  var cfg = window.SITE_CONFIG || {};

  var TITLES = {
    en: "NER Analyzer — Every space, served from the right network room",
    pt: "NER Analyzer — Cada espaço, atendido pela sala de rede certa"
  };
  var MSG = {
    en: {
      sending: "Sending…",
      ok: "Thank you! Your message is on its way. I'll reply to the e-mail you gave.",
      invalid: "Please fill in your name, a valid e-mail and the message.",
      fail: "The message could not be sent from here. ",
      mailto: "Send it from your e-mail app instead",
      mailtoTail: " (the text you wrote is already in it)."
    },
    pt: {
      sending: "Enviando…",
      ok: "Obrigado! Sua mensagem foi enviada. Vou responder no e-mail que você informou.",
      invalid: "Preencha seu nome, um e-mail válido e a mensagem.",
      fail: "Não foi possível enviar a mensagem por aqui. ",
      mailto: "Envie pelo seu aplicativo de e-mail",
      mailtoTail: " (o texto que você escreveu já vai preenchido)."
    }
  };

  function lang() { return root.getAttribute("data-lang") === "pt" ? "pt" : "en"; }

  // ---------- language ----------
  function applyLang(l) {
    root.setAttribute("data-lang", l);
    root.lang = l === "pt" ? "pt-BR" : "en";
    document.title = TITLES[l];
    document.querySelectorAll("[data-set-lang]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-set-lang") === l));
    });
    document.querySelectorAll("option[data-en]").forEach(function (o) {
      o.textContent = o.getAttribute("data-" + l);
    });
    document.querySelectorAll("[data-ph-en]").forEach(function (el) {
      el.setAttribute("placeholder", el.getAttribute("data-ph-" + l));
    });
    try { localStorage.setItem("ner-site-lang", l); } catch (e) { /* storage blocked: fine */ }
  }
  document.querySelectorAll("[data-set-lang]").forEach(function (b) {
    b.addEventListener("click", function () { applyLang(b.getAttribute("data-set-lang")); });
  });
  applyLang(lang());

  // ---------- mobile menu ----------
  var nav = document.getElementById("nav");
  var menuBtn = document.querySelector(".menu-btn");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    nav.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        nav.classList.remove("open");
        menuBtn.setAttribute("aria-expanded", "false");
      });
    });
  }

  // ---------- reveal on scroll ----------
  var items = document.querySelectorAll(".rv");
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  } else {
    root.classList.add("no-io");
  }

  var y = document.getElementById("year");
  if (y) { var now = new Date().getFullYear(); y.textContent = now > 2026 ? "2026–" + now : "2026"; }

  // ---------- contact form ----------
  var form = document.getElementById("contact-form");
  var status = document.getElementById("form-status");
  var sendBtn = document.getElementById("f-send");
  if (!form) return;

  function show(kind, html) {
    status.className = "status show " + kind;
    status.innerHTML = html;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function mailtoHref(d) {
    var body = d.message + "\n\n— " + d.name + (d.organisation ? " (" + d.organisation + ")" : "") + "\n" + d.email;
    return "mailto:" + (cfg.contactEmail || "") +
      "?subject=" + encodeURIComponent("[NER Analyzer] " + d.topic) +
      "&body=" + encodeURIComponent(body);
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var t = MSG[lang()];
    var f = form.elements; // not form.name: that is the form's own name attribute
    var d = {
      name: f.namedItem("name").value.trim(),
      email: f.namedItem("email").value.trim(),
      organisation: f.namedItem("organisation").value.trim(),
      topic: f.namedItem("topic").value,
      message: f.namedItem("message").value.trim()
    };
    if (f.namedItem("_honey").value) { show("ok", esc(t.ok)); form.reset(); return; } // bot: pretend success
    var emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(d.email);
    if (!d.name || !emailOk || d.message.length < 2) { show("err", esc(t.invalid)); return; }

    sendBtn.disabled = true;
    show("ok", esc(t.sending));

    var payload = {
      name: d.name,
      email: d.email,
      organisation: d.organisation || "-",
      topic: d.topic,
      message: d.message,
      language: lang(),
      _subject: "[NER Analyzer site] " + d.topic + " — " + d.name,
      _replyto: d.email,
      _template: "table",
      _captcha: "false"
    };

    var ctrl = "AbortController" in window ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 15000) : null;

    fetch(cfg.contactEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
      signal: ctrl ? ctrl.signal : undefined
    })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        var success = res.ok && (res.j.success === true || res.j.success === "true");
        if (!success) throw new Error((res.j && res.j.message) || "send failed");
        show("ok", esc(t.ok));
        form.reset();
      })
      .catch(function () {
        show("err", esc(t.fail) + '<a href="' + esc(mailtoHref(d)) + '">' + esc(t.mailto) + "</a>" + esc(t.mailtoTail));
      })
      .then(function () { if (timer) clearTimeout(timer); sendBtn.disabled = false; });
  });
})();
