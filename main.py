<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>台股掃描器</title>

<style>
body {
  font-family: "Microsoft JhengHei";
  background: #0f172a;
  color: white;
  padding: 20px;
}

button {
  padding: 10px 16px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
}

.card {
  background: #1e293b;
  padding: 12px;
  border-radius: 10px;
  margin-bottom: 10px;
  cursor: pointer;
}

.right {
  float: right;
}

</style>
</head>

<body>

<h1>台股掃描器</h1>

<button onclick="scan()">掃描股票</button>

<h2 id="status"></h2>

<div style="display:flex; gap:20px; margin-top:20px">

<div style="width:50%">
<h3>掃描結果</h3>
<div id="list"></div>
</div>

<div style="width:50%">
<h3>AI 分析</h3>
<div id="detail"></div>
</div>

</div>

<script>

const API_BASE = "https://stock-scanner-apiz.onrender.com";

// 股票中文名稱
const stockNames = {
  "2330":"台積電",
  "2317":"鴻海",
  "2454":"聯發科",
  "2303":"聯電",
  "2603":"長榮",
  "2882":"國泰金",
  "2891":"中信金",
  "2408":"南亞科",
  "2308":"台達電",
  "3231":"緯創",
  "3481":"群創",
  "2409":"友達",
  "2301":"光寶科",
  "2357":"華碩",
  "2382":"廣達",
  "2379":"瑞昱",
  "6669":"緯穎",
  "3034":"聯詠",
  "3711":"日月光",
  "2881":"富邦金"
};

let data = [];

async function scan() {
  document.getElementById("status").innerText = "掃描中...";

  try {
    const res = await fetch(API_BASE + "/scan");
    const json = await res.json();

    data = json.data;

    renderList();

    document.getElementById("status").innerText = "完成";
  } catch (e) {
    document.getElementById("status").innerText = "掃描失敗";
  }
}

function renderList() {
  const list = document.getElementById("list");

  list.innerHTML = "";

  data.forEach(s => {

    const name = stockNames[s.symbol] || "";

    const div = document.createElement("div");
    div.className = "card";

    div.innerHTML = `
      <b>${name} (${s.symbol})</b>
      <span class="right">${s.score}</span><br>
      價格: ${s.close} | 量: ${s.volume}
    `;

    div.onclick = () => analyze(s.symbol);

    list.appendChild(div);
  });
}

async function analyze(symbol) {
  document.getElementById("detail").innerText = "分析中...";

  try {
    const res = await fetch(API_BASE + "/ai/analyze", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ symbol })
    });

    const json = await res.json();

    document.getElementById("detail").innerText =
      json.llm_analysis || "無分析";

  } catch(e) {
    document.getElementById("detail").innerText = "分析失敗";
  }
}

</script>

</body>
</html>
