// NicheForge — Approval Inbox logic. Plain fetch, no frameworks.
(function () {
  "use strict";

  var nicheFilter = document.getElementById("nicheFilter");
  var statusFilter = document.getElementById("statusFilter");
  var ideasEl = document.getElementById("ideas");
  var countsEl = document.getElementById("counts");
  var addNiche = document.getElementById("addNiche");
  var addTitle = document.getElementById("addTitle");
  var addDetail = document.getElementById("addDetail");
  var addBtn = document.getElementById("addBtn");
  var msg = document.getElementById("msg");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function setMsg(text, ok) {
    msg.textContent = text || "";
    msg.className = ok ? "ok" : "err";
  }

  function api(path, opts) {
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return { error: "bad response" }; });
    });
  }

  function loadNiches() {
    api("/api/niches").then(function (data) {
      var niches = data.niches || [];
      [nicheFilter, addNiche].forEach(function (sel) {
        var keep = sel === nicheFilter ? sel.options[0] : null;
        sel.innerHTML = "";
        if (keep) sel.appendChild(keep);
        niches.forEach(function (n) {
          var o = document.createElement("option");
          o.value = n; o.textContent = n;
          sel.appendChild(o);
        });
      });
    }).catch(function () { setMsg("Could not load niches.", false); });
  }

  function loadIdeas() {
    var q = [];
    if (statusFilter.value) q.push("status=" + encodeURIComponent(statusFilter.value));
    if (nicheFilter.value) q.push("niche=" + encodeURIComponent(nicheFilter.value));
    ideasEl.innerHTML = '<div id="empty">Loading…</div>';
    api("/api/ideas" + (q.length ? "?" + q.join("&") : ""))
      .then(function (data) {
        if (data.error) { setMsg("Error: " + data.error, false); }
        var ideas = data.ideas || [];
        countsEl.textContent = ideas.length + " shown";
        if (!ideas.length) {
          ideasEl.innerHTML = '<div id="empty">No ideas match this filter.</div>';
          return;
        }
        ideasEl.innerHTML = "";
        ideas.forEach(function (idea) {
          var card = document.createElement("div");
          card.className = "card";
          card.innerHTML =
            '<span class="tag">' + esc(idea.niche) + '</span>' +
            '<h3>' + esc(idea.title) + '</h3>' +
            (idea.detail ? '<p>' + esc(idea.detail) + '</p>' : "") +
            '<div class="meta">#' + idea.id + ' · ' + esc(idea.created_at || "") +
            ' · ' + esc(idea.status) +
            ' <span class="score" data-idea="' + idea.id + '"></span></div>' +
            '<div class="actions">' +
              '<button class="approve">Approve</button>' +
              '<button class="reject">Reject</button>' +
            '</div>';
          var btnA = card.querySelector(".approve");
          var btnR = card.querySelector(".reject");
          if (idea.status !== "pending") {
            btnA.disabled = true; btnR.disabled = true;
            btnA.style.opacity = "0.4"; btnR.style.opacity = "0.4";
          } else {
            btnA.addEventListener("click", function () { decide(idea.id, "approve"); });
            btnR.addEventListener("click", function () { decide(idea.id, "reject"); });
          }
          ideasEl.appendChild(card);
        });
        paintScores();
      })
      .catch(function () {
        ideasEl.innerHTML = '<div id="empty">Could not load ideas.</div>';
      });
  }

  function paintScores() {
    // Predicted-performance badges from the intel layer. Silent on failure.
    api("/api/intel/ideas/scores").then(function (data) {
      var scores = data.scores || {};
      document.querySelectorAll("span.score[data-idea]").forEach(function (el) {
        var s = scores[el.getAttribute("data-idea")];
        if (s == null) return;
        var v = Math.round(Number(s));
        var cls = v >= 70 ? "hi" : (v >= 45 ? "mid" : "lo");
        el.innerHTML = ' <span class="sbadge ' + cls + '">★ ' + v + '</span>';
        el.title = "Predicted performance score (intel layer)";
      });
    }).catch(function () {});
  }

  function decide(id, action) {
    api("/api/ideas/" + id + "/" + action, { method: "POST" })
      .then(function (data) {
        if (data.ok) { setMsg("Idea #" + id + " " + data.status + ".", true); loadIdeas(); }
        else { setMsg("Could not update: " + (data.reason || "unknown"), false); }
      })
      .catch(function () { setMsg("Request failed.", false); });
  }

  addBtn.addEventListener("click", function () {
    var title = addTitle.value.trim();
    if (!addNiche.value) { setMsg("Pick a niche first.", false); return; }
    if (!title) { setMsg("Title is required.", false); return; }
    addBtn.disabled = true;
    api("/api/ideas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        niche: addNiche.value, title: title, detail: addDetail.value.trim()
      })
    }).then(function (data) {
      if (data.ok) {
        setMsg("Added as idea #" + data.id + ".", true);
        addTitle.value = ""; addDetail.value = "";
        loadIdeas();
      } else {
        // Duplicate (or other) server message — show it verbatim.
        setMsg(data.reason || "Rejected.", false);
      }
    }).catch(function () { setMsg("Request failed.", false); })
      .then(function () { addBtn.disabled = false; });
  });

  nicheFilter.addEventListener("change", loadIdeas);
  statusFilter.addEventListener("change", loadIdeas);

  loadNiches();
  loadIdeas();
})();
