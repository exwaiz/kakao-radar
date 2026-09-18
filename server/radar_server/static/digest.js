"use strict";
(() => {
  const delivery = location.pathname.split("/").pop();
  const key = new URLSearchParams(location.hash.slice(1)).get("key");
  const status = document.getElementById("status");
  const root = document.getElementById("topics");
  const endpoint = `/v1/digests/${encodeURIComponent(delivery)}`;
  const headers = { Authorization: `Digest ${key}`, "Content-Type": "application/json" };
  const node = (tag, text, cls) => {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (cls) item.className = cls;
    return item;
  };
  async function request(url, options = {}) {
    const result = await fetch(url, { ...options, headers, cache: "no-store", credentials: "omit", redirect: "error" });
    if (!result.ok) throw new Error("unavailable");
    return result.json();
  }
  function show(topic) {
    const card = node("article");
    card.append(node("h2", topic.payload.title));
    const points = node("ul");
    for (const point of topic.payload.points) points.append(node("li", point.text));
    card.append(points);
    if (topic.payload.uncertainty !== "none") card.append(node("p", "문맥이 제한되거나 내용이 엇갈립니다. 근거를 확인하세요.", "caveat"));
    for (const source of topic.payload.source_urls) {
      try {
        const url = new URL(source);
        if (!["https:", "http:"].includes(url.protocol)) continue;
        const link = node("a", `관련 링크 · ${url.hostname}`);
        link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer";
        const paragraph = node("p");
        paragraph.append(link); card.append(paragraph);
      } catch { /* Invalid URLs remain non-interactive. */ }
    }
    const evidence = node("details");
    evidence.append(node("summary", `근거 ${topic.evidence.length}개 확인`));
    for (const source of topic.evidence) {
      evidence.append(source.availability === "available"
        ? node("blockquote", source.text) : node("p", "원문 보관 기간이 지나 이 근거를 볼 수 없습니다.", "notice"));
    }
    card.append(evidence);
    const feedbackStatus = node("p", topic.rating ? "기록된 피드백이 있습니다." : "", "feedback-status");
    feedbackStatus.setAttribute("role", "status");
    const buttons = [];
    for (const [rating, label] of [["useful", "유용함"], ["not_interested", "관심 없음"]]) {
      const button = node("button", label);
      button.type = "button";
      button.setAttribute("aria-pressed", String(topic.rating === rating));
      button.addEventListener("click", async () => {
        buttons.forEach(b => { b.disabled = true; });
        try {
          await request(`${endpoint}/summaries/${encodeURIComponent(topic.summary_id)}/feedback`, { method: "PUT", body: JSON.stringify({ rating }) });
          buttons.forEach(b => b.setAttribute("aria-pressed", String(b === button)));
          feedbackStatus.textContent = "피드백을 저장했습니다.";
        } catch { feedbackStatus.textContent = "저장하지 못했습니다. 링크가 만료됐거나 연결이 끊겼을 수 있습니다."; }
        finally { buttons.forEach(b => { b.disabled = false; }); }
      });
      buttons.push(button); card.append(button);
    }
    card.append(feedbackStatus); root.append(card);
  }
  if (!key || !/^[a-f0-9]{64}$/.test(key)) {
    status.textContent = "알림에 포함된 요약 링크를 열어주세요.";
    return;
  }
  request(endpoint).then(data => {
    document.querySelector("h1").textContent = data.title;
    status.textContent = data.status === "uncertain" ? "이 요약의 채널 발송 결과는 아직 확인되지 않았습니다." : "";
    data.topics.forEach(show);
    request(`${endpoint}/opened`, { method: "POST" }).catch(() => {});
  }).catch(() => { status.textContent = "요약을 열 수 없습니다. 링크 만료, 데이터 삭제 또는 연결 상태를 확인하세요."; });
})();
