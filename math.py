import sys
!{sys.executable} -m pip install pyvis requests networkx

"""
math_graph_crawler.py
─────────────────────
Constrói um grafo interativo de conhecimento matemático
a partir da Wikipedia, usando a API MediaWiki pública.

Dependências:
    pip install requests networkx pyvis

Uso:
    python math_graph_crawler.py
    # Ou ajuste os parâmetros em CONFIG antes de rodar.
"""

import time
import re
import json
import math
import requests
import networkx as nx
from pyvis.network import Network
from collections import deque

# ─── CONFIGURAÇÃO ─────────────────────────────────────────────────────────────

CONFIG = {
    # Artigo raiz da exploração
    "start_page": "Mathematics",

    # Profundidade do BFS (1 = só vizinhos diretos, 2 = vizinhos dos vizinhos…)
    "max_depth": 2,

    # Máximo de nós no grafo final
    "max_nodes": 120,

    # Máximo de links extraídos por página (evita explosão combinatória)
    "links_per_page": 30,

    # Delay entre requisições à API (seja gentil com a Wikipedia!)
    "request_delay": 0.15,   # segundos

    # Arquivo de saída HTML
    "output_file": "math_knowledge_graph.html",

    # Palavras-chave de INCLUSÃO — ao menos uma deve aparecer no título ou resumo
    # Deixe lista vazia para aceitar todo artigo que passe nos filtros de exclusão
    "math_keywords": [
        "theorem", "algebra", "geometry", "topology", "calculus",
        "analysis", "number", "equation", "function", "space",
        "group", "ring", "field", "matrix", "vector", "graph",
        "logic", "set", "proof", "prime", "manifold", "integral",
        "derivative", "probability", "statistics", "combinatorics",
        "category", "operator", "polynomial", "differential",
        "arithmetic", "trigonometry", "series", "sequence",
        "transformation", "symmetry", "invariant", "dimension",
        "complex", "real", "rational", "integer", "finite",
        "infinite", "discrete", "continuous", "linear", "nonlinear",
        "mathematical", "mathematics",
    ],

    # Padrões de EXCLUSÃO — links com estes padrões são descartados
    "exclude_patterns": [
        r"^\d{4}",                          # começa com ano
        r"^List_of",                        # listas
        r"^Portal:",                        # portais
        r"^Category:",                      # categorias
        r"^Template:",                      # templates
        r"^Wikipedia:",                     # páginas internas
        r"^Help:",                          # help
        r"^Talk:",                          # discussão
        r"^File:",                          # arquivos
        r"^Image:",                         # imagens
        r"^Special:",                       # páginas especiais
        r"_(disambiguation)$",             # desambiguação
        r"^(January|February|March|April|May|June|"
        r"July|August|September|October|November|December)",
        r"^(Afghan|African|Albanian|American|Arab|Argentine|"
        r"Armenian|Asian|Australian|Austrian|Belgian|Bolivian|"
        r"Brazilian|British|Bulgarian|Canadian|Chilean|Chinese|"
        r"Colombian|Croatian|Czech|Danish|Dutch|Egyptian|English|"
        r"Ethiopian|European|Filipino|Finnish|French|Georgian|German|"
        r"Greek|Hungarian|Indian|Indonesian|Iranian|Iraqi|Irish|"
        r"Israeli|Italian|Japanese|Jordanian|Kazakh|Korean|Lebanese|"
        r"Lithuanian|Malaysian|Mexican|Moroccan|Norwegian|Pakistani|"
        r"Peruvian|Polish|Portuguese|Romanian|Russian|Saudi|Serbian|"
        r"Slovak|South|Soviet|Spanish|Swedish|Swiss|Syrian|Thai|"
        r"Turkish|Ukrainian|Venezuelan|Vietnamese)",
    ],

# Categorias temáticas para colorir nós (regex aplicado ao título)
    "topic_colors": {
        "Algebra":        ("#4f9cf9", ["algebra", "group", "ring", "field", "polynomial",
                                       "galois", "linear", "vector", "module", "lattice"]),
        "Analysis":       ("#f97b4f", ["analysis", "calculus", "integral", "derivative",
                                       "function", "measure", "series", "convergence",
                                       "differential equation", "fourier"]),
        "Geometry":       ("#a3f97b", ["geometry", "topology", "manifold", "space",
                                       "curve", "surface", "metric", "dimension",
                                       "euclidean", "hyperbolic", "projective"]),
        "Number Theory":  ("#f7c948", ["number", "prime", "integer", "arithmetic",
                                       "diophantine", "modular", "elliptic curve",
                                       "riemann", "zeta", "congruence"]),
        "Logic & Sets":   ("#c77dff", ["logic", "set theory", "proof", "formal",
                                       "axiom", "theorem", "model theory", "category theory",
                                       "type theory", "computability"]),
        "Probability":    ("#ff6b9d", ["probability", "statistics", "stochastic",
                                       "random", "bayesian", "distribution",
                                       "markov", "game theory"]),
        "Combinatorics":  ("#4ecdc4", ["combinatorics", "graph theory", "discrete",
                                       "permutation", "partition", "matroid", "coding"]),
        "Mathematics":    ("#e2e8f0", []),   # cor padrão (artigos genéricos)
    },
}

# ─── API WIKIPEDIA ─────────────────────────────────────────────────────────────

BASE_API = "https://en.wikipedia.org/w/api.php"
BASE_URL  = "https://en.wikipedia.org/wiki/"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "MathKnowledgeGraphBot/1.0 (educational project; contact@example.com)"
})

def wiki_links(title: str, limit: int = 50) -> list[str]:
    """Retorna links internos da Wikipedia para o artigo `title`."""
    params = {
        "action":   "query",
        "titles":   title,
        "prop":     "links",
        "pllimit":  limit,
        "plnamespace": 0,          # somente artigos (namespace 0)
        "format":   "json",
        "redirects": 1,
    }
    try:
        resp = SESSION.get(BASE_API, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            return [lk["title"] for lk in page.get("links", [])]
    except Exception as e:
        print(f"  [WARN] Falha ao buscar links de '{title}': {e}")
    return []


def wiki_summary(title: str) -> dict:
    """Retorna sumário (extract + info) de um artigo via API REST."""
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}"
    try:
        resp = SESSION.get(url, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [WARN] Falha ao buscar sumário de '{title}': {e}")
    return {}

# ─── FILTROS ───────────────────────────────────────────────────────────────────

_exclude_re = [re.compile(p, re.IGNORECASE) for p in CONFIG["exclude_patterns"]]
_math_kw    = [kw.lower() for kw in CONFIG["math_keywords"]]


def is_excluded(title: str) -> bool:
    """True se o título deve ser ignorado pelos padrões de exclusão."""
    slug = title.replace(" ", "_")
    return any(rx.search(slug) for rx in _exclude_re)


def is_math_relevant(title: str, summary_text: str = "") -> bool:
    """True se o artigo parece ser sobre matemática."""
    if not _math_kw:
        return True                         # sem filtro → aceita tudo
    haystack = (title + " " + summary_text).lower()
    return any(kw in haystack for kw in _math_kw)


# ─── CLASSIFICADOR TEMÁTICO ────────────────────────────────────────────────────

def classify_node(title: str, summary: str = "") -> str:
    """Retorna o nome do tópico temático mais adequado para o nó."""
    haystack = (title + " " + summary).lower()
    best, best_score = "Mathematics", 0
    for topic, (color, keywords) in CONFIG["topic_colors"].items():
        if topic == "Mathematics":
            continue
        score = sum(1 for kw in keywords if kw in haystack)
        if score > best_score:
            best, best_score = topic, score
    return best


# ─── CRAWLER BFS ───────────────────────────────────────────────────────────────

def crawl(start: str, max_depth: int, max_nodes: int,
          links_per_page: int, delay: float) -> tuple[nx.DiGraph, dict]:
    """
    BFS a partir de `start`, retorna:
      - G: DiGraph com artigos como nós e hiperlinks como arestas
      - meta: dicionário title → {summary, url, topic}
    """
    G    = nx.DiGraph()
    meta = {}

    queue   = deque([(start, 0)])          # (título, profundidade)
    visited = {start}

    print(f"\n🔍 Iniciando crawl em '{start}' | depth={max_depth} | max_nodes={max_nodes}\n")

    while queue and len(G.nodes) < max_nodes:
        title, depth = queue.popleft()

        print(f"  {'  ' * depth}→ {title}  (depth={depth}, nós={len(G.nodes)})")

        # ── Sumário ──────────────────────────────────────────────────────────
        time.sleep(delay)
        summ  = wiki_summary(title)
        text  = summ.get("extract", "")[:300]
        topic = classify_node(title, text)

        meta[title] = {
            "summary": summ.get("extract", "Sem descrição disponível.")[:400],
            "url":     summ.get("content_urls", {}).get("desktop", {}).get("page",
                               BASE_URL + requests.utils.quote(title.replace(" ", "_"))),
            "topic":   topic,
        }

        G.add_node(title, topic=topic)

        if depth >= max_depth:
            continue

        # ── Links ─────────────────────────────────────────────────────────────
        time.sleep(delay)
        links = wiki_links(title, limit=links_per_page * 4)   # busca extra para compensar filtros

        accepted = 0
        for link in links:
            if accepted >= links_per_page:
                break
            if is_excluded(link):
                continue
            if not is_math_relevant(link):
                continue

            G.add_edge(title, link)

            if link not in visited and len(G.nodes) < max_nodes:
                visited.add(link)
                queue.append((link, depth + 1))
            accepted += 1

    print(f"\n✅ Crawl concluído — {len(G.nodes)} nós, {len(G.edges)} arestas.\n")
    return G, meta

# ─── MÉTRICAS DE CENTRALIDADE ──────────────────────────────────────────────────

def compute_centrality(G: nx.DiGraph) -> dict[str, float]:
    """PageRank normalizado [0..1] para escalar o tamanho dos nós."""
    try:
        pr = nx.pagerank(G, alpha=0.85, max_iter=200)
    except Exception:
        pr = {n: 1.0 for n in G.nodes()}

    max_val = max(pr.values()) or 1.0
    return {k: v / max_val for k, v in pr.items()}


# ─── VISUALIZAÇÃO PYVIS ────────────────────────────────────────────────────────

def build_html(G: nx.DiGraph, meta: dict, centrality: dict, output: str) -> None:
    """Constrói o arquivo HTML interativo com Pyvis."""

    net = Network(
        height="100vh",
        width="100%",
        bgcolor="#0d1117",
        font_color="#e2e8f0",
        directed=True,
        notebook=False,
        cdn_resources="in_line",    # HTML autocontido, sem dependência de CDN
    )

    # ── Física do grafo ───────────────────────────────────────────────────────
    net.set_options("""
    {
      "physics": {
        "enabled": true,
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 120,
          "springConstant": 0.08,
          "damping": 0.4,
          "avoidOverlap": 0.8
        },
        "stabilization": {
          "enabled": true,
          "iterations": 200,
          "updateInterval": 25
        }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 150,
        "hideEdgesOnDrag": true,
        "navigationButtons": false,
        "keyboard": { "enabled": true }
      },
      "edges": {
        "smooth": { "enabled": true, "type": "dynamic" },
        "color": { "inherit": "from" },
        "width": 0.8,
        "arrows": { "to": { "enabled": true, "scaleFactor": 0.4 } }
      },
      "nodes": {
        "shape": "dot",
        "font": {
          "face": "IBM Plex Mono",
          "size": 11
        },
        "borderWidth": 1.5,
        "shadow": { "enabled": true, "size": 8, "x": 2, "y": 2 }
      }
    }
    """)


# ─── INJEÇÃO DE MELHORIAS NO HTML ─────────────────────────────────────────────

def _inject_enhancements(html: str, G: nx.DiGraph, meta: dict,
                          topic_colors: dict) -> str:
    """
    Injeta no HTML gerado pelo Pyvis:
      • Painel de informações ao clicar em nós
      • Legenda temática
      • Barra de busca por nó
      • Fontes Google (IBM Plex Mono)
      • Estilo visual aprimorado
    """
    # Dados de nós para o painel lateral (JSON embutido)
    node_data = {
        n: {
            "summary": meta.get(n, {}).get("summary", ""),
            "url":     meta.get(n, {}).get("url", ""),
            "topic":   meta.get(n, {}).get("topic", "Mathematics"),
            "degree":  G.in_degree(n),
        }
        for n in G.nodes()
    }

    legend_items = "".join(
        f'<div class="leg-item"><span class="leg-dot" style="background:{c}"></span>'
        f'<span>{topic}</span></div>'
        for topic, c in topic_colors.items()
        if topic != "Mathematics"
    )
    legend_items += (
        f'<div class="leg-item"><span class="leg-dot" '
        f'style="background:#e2e8f0"></span><span>Other / General</span></div>'
    )

    injection = f"""
<!-- ═══════ MATH GRAPH ENHANCEMENTS ═══════ -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;600&family=Space+Grotesk:wght@300;400;600&display=swap" rel="stylesheet">

<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #0d1117;
    font-family: 'Space Grotesk', sans-serif;
    color: #e2e8f0;
    overflow: hidden;
  }}

  /* ── Cabeçalho ── */
  #header {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 100;
    display: flex; align-items: center; gap: 16px;
    padding: 10px 20px;
    background: rgba(13,17,23,0.92);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}

  #header h1 {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 14px; font-weight: 600;
    color: #4f9cf9; letter-spacing: 0.08em;
    white-space: nowrap;
  }}

  #header h1 span {{ color: #94a3b8; font-weight: 300; }}

  #search-box {{
    flex: 1; max-width: 320px;
    background: #1e2433; border: 1px solid #2d3748;
    border-radius: 6px; padding: 6px 12px;
    color: #e2e8f0; font-family: 'IBM Plex Mono', monospace;
    font-size: 12px; outline: none;
    transition: border-color .2s;
  }}
  #search-box:focus {{ border-color: #4f9cf9; }}
  #search-box::placeholder {{ color: #4a5568; }}

  #stats {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: #4a5568;
    white-space: nowrap;
  }}
/* ── Painel lateral ── */
  #side-panel {{
    position: fixed; top: 54px; right: 0;
    width: 300px; height: calc(100vh - 54px);
    background: rgba(13,17,23,0.95);
    backdrop-filter: blur(12px);
    border-left: 1px solid rgba(255,255,255,0.06);
    padding: 20px; overflow-y: auto;
    transform: translateX(100%);
    transition: transform .3s cubic-bezier(.4,0,.2,1);
    z-index: 90;
  }}

  #side-panel.open {{ transform: translateX(0); }}

  #panel-topic {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; font-weight: 600;
    letter-spacing: .12em; text-transform: uppercase;
    margin-bottom: 6px;
  }}

  #panel-title {{
    font-size: 17px; font-weight: 600;
    margin-bottom: 12px; line-height: 1.3;
    color: #f1f5f9;
  }}

  #panel-summary {{
    font-size: 12.5px; color: #94a3b8;
    line-height: 1.65; margin-bottom: 18px;
  }}

  #panel-degree {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px; color: #4a5568;
    margin-bottom: 16px;
  }}

  #panel-link {{
    display: inline-block;
    background: #1e2d45; border: 1px solid #4f9cf9;
    color: #4f9cf9; border-radius: 5px;
    padding: 7px 14px; font-size: 12px;
    text-decoration: none; font-weight: 600;
    transition: background .2s;
  }}
  #panel-link:hover {{ background: #4f9cf9; color: #0d1117; }}

  #panel-close {{
    position: absolute; top: 14px; right: 14px;
    background: none; border: none; color: #4a5568;
    font-size: 20px; cursor: pointer; line-height: 1;
    transition: color .2s;
  }}
  #panel-close:hover {{ color: #e2e8f0; }}

 /* ── Legenda ── */
  #legend {{
    position: fixed; bottom: 20px; left: 20px;
    background: rgba(13,17,23,0.92);
    backdrop-filter: blur(8px);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px; padding: 14px 16px;
    z-index: 90; min-width: 180px;
  }}

  #legend h3 {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px; letter-spacing: .14em;
    text-transform: uppercase; color: #4a5568;
    margin-bottom: 10px;
  }}

  .leg-item {{
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; color: #94a3b8; margin-bottom: 5px;
  }}

  .leg-dot {{
    width: 9px; height: 9px; border-radius: 50%;
    flex-shrink: 0;
  }}

  /* ── Hint ── */
  #hint {{
    position: fixed; bottom: 20px; right: 20px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px; color: #2d3748; text-align: right;
    z-index: 90; line-height: 1.8;
  }}

  /* ── Ajuste do canvas Pyvis ── */
  #mynetwork {{
    position: fixed !important;
    top: 54px !important;
    left: 0 !important;
    width: 100% !important;
    height: calc(100vh - 54px) !important;
  }}
</style>

<!-- HEADER -->
<div id="header">
  <h1>∑ Math Knowledge Graph <span>/ Wikipedia</span></h1>
  <input id="search-box" type="text" placeholder="buscar nó…" autocomplete="off">
  <span id="stats">
    {len(G.nodes())} nodes · {len(G.edges())} edges
  </span>
</div>

<!-- PAINEL LATERAL -->
<div id="side-panel">
  <button id="panel-close" onclick="closePanel()">×</button>
  <div id="panel-topic"></div>
  <div id="panel-title">Selecione um nó</div>
  <div id="panel-summary"></div>
  <div id="panel-degree"></div>
  <a id="panel-link" href="#" target="_blank" rel="noopener">
    Abrir na Wikipedia ↗
  </a>
</div>

<!-- LEGENDA -->
<div id="legend">
  <h3>Tópicos</h3>
  {legend_items}
</div>

<!-- HINT -->
<div id="hint">
  scroll: zoom<br>
  drag: mover<br>
  click: detalhes
</div>

<script>
// ── Dados embutidos ────────────────────────────────────────────────────────
const NODE_DATA = {json.dumps(node_data, ensure_ascii=False)};

const TOPIC_COLORS = {json.dumps(topic_colors)};


// ── Painel ─────────────────────────────────────────────────────────────────
function openPanel(nodeId) {{
  const d = NODE_DATA[nodeId];
  if (!d) return;
  const color = TOPIC_COLORS[d.topic] || '#e2e8f0';
  document.getElementById('panel-topic').style.color  = color;
  document.getElementById('panel-topic').textContent  = d.topic;
  document.getElementById('panel-title').textContent  = nodeId;
  document.getElementById('panel-summary').textContent = d.summary || 'Sem descrição.';
  document.getElementById('panel-degree').textContent =
    `Links recebidos: ${{d.degree}}`;
  const lnk = document.getElementById('panel-link');
  lnk.href = d.url || '#';
  lnk.style.borderColor = color;
  lnk.style.color = color;
  document.getElementById('side-panel').classList.add('open');
}}

function closePanel() {{
  document.getElementById('side-panel').classList.remove('open');
}}

// ── Conecta evento de clique do Pyvis ──────────────────────────────────────
// Pyvis expõe a instância vis.Network como `network` no escopo global.
// Aguardamos o objeto estar disponível.
function hookNetworkEvents() {{
  if (typeof network === 'undefined') {{
    setTimeout(hookNetworkEvents, 200);
    return;
  }}
  network.on('click', function(params) {{
    if (params.nodes.length > 0) {{
      openPanel(params.nodes[0]);
    }}
  }});
  network.on('doubleClick', function(params) {{
    if (params.nodes.length > 0) {{
      const d = NODE_DATA[params.nodes[0]];
      if (d && d.url) window.open(d.url, '_blank');
    }}
  }});
}}

document.addEventListener('DOMContentLoaded', hookNetworkEvents);


// ── Busca de nó ────────────────────────────────────────────────────────────
document.getElementById('search-box').addEventListener('input', function() {{
  const q = this.value.trim().toLowerCase();
  if (!q || typeof network === 'undefined') return;

  const match = Object.keys(NODE_DATA).find(n => n.toLowerCase().includes(q));
  if (match) {{
    const positions = network.getPositions([match]);
    if (positions[match]) {{
      network.moveTo({
        position: positions[match],
        scale: 1.6,
        animation: {{ duration: 600, easingFunction: 'easeInOutQuad' }},
      });
      network.selectNodes([match]);
      openPanel(match);
    }}
  }}
}});
</script>
<!-- ═══════ END ENHANCEMENTS ═══════ -->
"""

    # Injeta antes de </body>
    if "</body>" in html:
        html = html.replace("</body>", injection + "\n</body>")
    else:
        html += injection

    return html

# ─── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

def main() -> None:
    cfg = CONFIG

    # 1. Crawl BFS
    G, meta = crawl(
        start        = cfg["start_page"],
        max_depth    = cfg["max_depth"],
        max_nodes    = cfg["max_nodes"],
        links_per_page = cfg["links_per_page"],
        delay         = cfg["request_delay"],
    )

    # 2. Remove nós sem metadado (nunca foram visitados como fonte)
    #    — mantém somente nós com pelo menos 1 aresta
    isolates = list(nx.isolates(G))
    if isolates:
        print(f"  ℹ Removendo {len(isolates)} nós isolados.")
        G.remove_nodes_from(isolates)

    # 3. Preenche metadados faltantes com sumário rápido
    for node in list(G.nodes()):
        if node not in meta:
            time.sleep(cfg["request_delay"])
            summ = wiki_summary(node)
            meta[node] = {
                "summary": summ.get("extract", "")[:400],
                "url":     summ.get("content_urls", {}).get("desktop", {}).get(
                               "page", BASE_URL + node.replace(" ", "_")),
                "topic":   classify_node(node, summ.get("extract", "")),
            }
            G.nodes[node]["topic"] = meta[node]["topic"]

    # 4. Centralidade
    centrality = compute_centrality(G)

    # 5. Visualização
    build_html(G, meta, centrality, cfg["output_file"])

    # 6. Estatísticas finais
    print("\n── Estatísticas ─────────────────────────────────────")
    print(f"  Nós:    {len(G.nodes())}")
    print(f"  Arestas:{len(G.edges())}")
    top5 = sorted(centrality.items(), key=lambda x: -x[1])[:5]
    print("  Top-5 por PageRank:")
    for name, score in top5:
        print(f"    • {name:40s}  {score:.3f}")
    print(f"\n  → Abra '{cfg['output_file']}' no seu browser.\n")


if __name__ == "__main__":
    main()