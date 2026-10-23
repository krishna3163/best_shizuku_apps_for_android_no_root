"""Build a modern, PostHog-styled searchable HTML catalog from the README tables."""

import json
import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

ROW = re.compile(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| (.+) \|\s*$")
HEADING = re.compile(r"^(#{2,3})\s+(.+)$")


def parse_catalog() -> list[dict]:
    content = README.read_text(encoding="utf-8")
    # Exclude auto-generated download, update, discovery, and stats sections
    content = re.sub(
        r"<!-- (AUTO-DISCOVERED-SHIZUKU-APPS|AUTO-GENERATED-APPS|RECENT-UPDATES|STATS-GRAPH)[^>]* -->.*?<!-- \1[^>]* -->",
        "",
        content,
        flags=re.DOTALL,
    )
    entries = []
    current_category = "General"
    is_top_picks = False

    for line in content.splitlines():
        h_match = HEADING.match(line)
        if h_match:
            title = h_match.group(2).strip()
            # Clean title
            clean_title = re.sub(r"^[^\w\s]+", "", title).strip()
            if "Top Picks" in title or "Picks" in title:
                is_top_picks = True
                current_category = "Top Picks"
            elif title.startswith("Apps") or title.startswith("## Apps"):
                is_top_picks = False
                current_category = "General"
            else:
                current_category = clean_title or title
            continue

        r_match = ROW.match(line)
        if r_match:
            raw_name = r_match.group(1).strip()
            desc = r_match.group(2).strip()
            license_type = r_match.group(3).strip()
            raw_links = r_match.group(4).strip()

            if raw_name in {"App", "---", ":---", "Library"} or desc == "Description":
                continue

            # Extract primary URL
            url_match = re.search(r"\((https?://[^)]+)\)", raw_name)
            if not url_match:
                url_match = re.search(r"\((https?://[^)]+)\)", raw_links)
            primary_url = url_match.group(1) if url_match else "#"

            # Clean name (strip markdown asterisks, brackets, URLs)
            clean_name = re.sub(r"\[|\]|\*|\([^)]+\)", "", raw_name).strip()
            is_featured = "⭐" in raw_name or is_top_picks

            # Parse all individual links
            parsed_links = []
            for link_label, link_url in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", raw_links):
                parsed_links.append({"label": link_label.strip(), "url": link_url.strip()})
            if not parsed_links and primary_url != "#":
                parsed_links.append({"label": "Project Page", "url": primary_url})

            # Normalize category name
            cat = current_category
            if cat.startswith("Essential Apps") or cat.startswith("Privacy & Utility"):
                cat = "Top Picks"

            entries.append({
                "name": clean_name,
                "url": primary_url,
                "description": desc,
                "license": license_type if license_type else "See project",
                "links": parsed_links,
                "category": cat,
                "featured": is_featured
            })

    # Include Morphe releases
    morphe_path = ROOT / "data" / "morphe-releases.json"
    if morphe_path.exists():
        try:
            with open(morphe_path, "r", encoding="utf-8") as f:
                morphe_db = json.load(f)
            for slug, item in morphe_db.items():
                name = item.get("name", slug)
                tag = item.get("release_tag", "")
                download_url = f"https://github.com/krishna3163/best_shizuku_apps_for_android_no_root/releases/tag/{tag}"
                bundle_url = f"https://github.com/{item.get('bundle_repo', '')}"
                build_type = item.get("build_type", "autobuild")
                channel = item.get("channel", "stable")
                patches = ", ".join(item.get("patches", [])[:3])
                desc = f"[{build_type.upper()}] [{channel.upper()}] Patched with {item.get('bundle_name', 'Morphe')}. Key Patches: {patches}. SHA-256: {item.get('sha256', '')[:10]}..."
                entries.append({
                    "name": f"⚡ {name}",
                    "url": download_url,
                    "description": desc,
                    "license": "Morphe Patched APK",
                    "links": [
                        {"label": "⬇️ Download APK", "url": download_url},
                        {"label": "Bundle Source", "url": bundle_url},
                    ],
                    "category": "⚡ Morphe Patched Apps",
                    "featured": True,
                })
        except Exception as exc:
            print(f"Error loading Morphe releases: {exc}")

    return entries


def build_html():
    entries = parse_catalog()

    # Collect category counts
    categories_dict = {}
    for e in entries:
        c = e["category"]
        categories_dict[c] = categories_dict.get(c, 0) + 1

    sorted_categories = sorted(categories_dict.keys(), key=lambda k: (-categories_dict[k], k))

    # JSON payload for fast client-side searching
    json_data = json.dumps(entries, ensure_ascii=False)

    html_content = f'''<!doctype html>
<html lang="en" class="scroll-smooth">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Best Shizuku Apps for Android (No Root) — PostHog Style Catalog</title>
  <meta name="description" content="Discover 350+ curated no-root Android apps, wireless ADB utilities, debloat tools, and system modifiers powered by the Shizuku Binder API.">
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cpath d='M50 15 C50 15 25 45 25 65 C25 78 36 86 50 86 C64 86 75 78 75 65 C75 45 50 15 50 15 Z' fill='%23ffd000' stroke='%231d1b16' stroke-width='6'/%3E%3Ccircle cx='42' cy='62' r='4' fill='%231d1b16'/%3E%3Ccircle cx='58' cy='62' r='4' fill='%231d1b16'/%3E%3Cpath d='M47 70 Q50 74 53 70' stroke='%231d1b16' stroke-width='3.5' fill='none'/%3E%3C/svg%3E">
  
  <!-- Fonts -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  
  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{
            paper: '#fcfaf6',
            ink: '#1d1b16',
            postyellow: '#ffd000',
            postamber: '#f5a623',
            badgebrown: '#666053',
            badgeyellow: '#fff3b0'
          }},
          fontFamily: {{
            sans: ['Inter', 'system-ui', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace']
          }},
          boxShadow: {{
            'brutal-sm': '2px 2px 0px #1d1b16',
            'brutal': '3px 3px 0px #1d1b16',
            'brutal-lg': '5px 5px 0px #1d1b16',
            'brutal-hover': '6px 6px 0px #1d1b16'
          }}
        }}
      }}
    }}
  </script>

  <!-- Canvas Confetti -->
  <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js"></script>

  <style>
    body {{
      background-color: #fcfaf6;
      color: #1d1b16;
      background-image: radial-gradient(#e5dfd3 1px, transparent 1px);
      background-size: 24px 24px;
    }}
    .neo-border {{
      border: 2px solid #1d1b16;
    }}
    .neo-shadow {{
      box-shadow: 4px 4px 0px #1d1b16;
    }}
    .neo-shadow-sm {{
      box-shadow: 2px 2px 0px #1d1b16;
    }}
    .neo-shadow-lg {{
      box-shadow: 6px 6px 0px #1d1b16;
    }}
    .posthog-btn-yellow {{
      background-color: #ffd000;
      color: #1d1b16;
      border: 2px solid #1d1b16;
      box-shadow: 3px 3px 0px #1d1b16;
      font-weight: 700;
      transition: all 0.15s ease;
    }}
    .posthog-btn-yellow:hover {{
      background-color: #ffe033;
      transform: translate(-1px, -1px);
      box-shadow: 4px 4px 0px #1d1b16;
    }}
    .posthog-btn-yellow:active {{
      transform: translate(2px, 2px);
      box-shadow: 1px 1px 0px #1d1b16;
    }}
    .posthog-btn-white {{
      background-color: #ffffff;
      color: #1d1b16;
      border: 2px solid #1d1b16;
      box-shadow: 3px 3px 0px #1d1b16;
      font-weight: 700;
      transition: all 0.15s ease;
    }}
    .posthog-btn-white:hover {{
      background-color: #f7f4ed;
      transform: translate(-1px, -1px);
      box-shadow: 4px 4px 0px #1d1b16;
    }}
    .posthog-btn-white:active {{
      transform: translate(2px, 2px);
      box-shadow: 1px 1px 0px #1d1b16;
    }}
    .active-pill {{
      background-color: #ffd000 !important;
      color: #1d1b16 !important;
      border-color: #1d1b16 !important;
      box-shadow: 2px 2px 0px #1d1b16 !important;
    }}
    /* Custom Scrollbar */
    ::-webkit-scrollbar {{
      width: 10px;
      height: 10px;
    }}
    ::-webkit-scrollbar-track {{
      background: #fcfaf6;
      border-left: 2px solid #1d1b16;
    }}
    ::-webkit-scrollbar-thumb {{
      background: #ffd000;
      border: 2px solid #1d1b16;
      border-radius: 4px;
    }}
  </style>
</head>

<body class="selection:bg-[#ffd000] selection:text-[#1d1b16] min-h-screen flex flex-col">

  <!-- Top Retro Announcement Bar -->
  <div class="bg-[#ffd000] border-b-2 border-[#1d1b16] py-2 px-4 text-center font-mono text-xs font-bold text-[#1d1b16] flex items-center justify-center gap-2">
    <span class="w-2 h-2 rounded-full bg-[#1d1b16] animate-ping"></span>
    <span>⚡ 350+ Curated No-Root Shizuku Apps & Tools • PostHog Retro Edition</span>
    <span class="hidden sm:inline text-black/60">•</span>
    <a href="https://shizuku-web.onrender.com" target="_blank" class="hidden sm:inline underline hover:text-[#f5a623] font-bold">
      Try Shizuku Web Companion →
    </a>
  </div>

  <!-- Sticky PostHog Navbar -->
  <header class="sticky top-0 z-40 bg-[#fcfaf6]/95 backdrop-blur-md border-b-2 border-[#1d1b16]">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-18 flex items-center justify-between">
      
      <!-- Brand & Mascot -->
      <div class="flex items-center gap-3.5 cursor-pointer" onclick="triggerMascotConfetti()">
        <div class="w-10 h-10 rounded-xl bg-[#ffd000] border-2 border-[#1d1b16] shadow-brutal-sm flex items-center justify-center overflow-hidden transform hover:-rotate-6 transition-transform">
          <svg viewBox="0 0 100 100" class="w-8 h-8">
            <path d="M50 15 C50 15 25 45 25 65 C25 78 36 86 50 86 C64 86 75 78 75 65 C75 45 50 15 50 15 Z" fill="#ffffff" stroke="#1d1b16" stroke-width="6" stroke-linejoin="round"/>
            <circle cx="42" cy="62" r="4" fill="#1d1b16"/>
            <circle cx="58" cy="62" r="4" fill="#1d1b16"/>
            <path d="M47 70 Q50 74 53 70" stroke="#1d1b16" stroke-width="3.5" stroke-linecap="round" fill="none"/>
          </svg>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="font-black text-xl sm:text-2xl tracking-tight text-[#1d1b16]">Shizuku Catalog</span>
            <span class="bg-[#fff3b0] text-[#1d1b16] text-[11px] font-mono font-bold px-2 py-0.5 rounded border border-[#1d1b16]">350+ Apps</span>
          </div>
          <span class="text-xs text-[#666053] font-medium hidden sm:block">No-Root Android Ecosystem Directory</span>
        </div>
      </div>

      <!-- Center & Right Navigation -->
      <div class="flex items-center gap-3">
        <!-- Search Quick Key -->
        <button onclick="focusSearch()" class="hidden md:flex items-center gap-2 bg-[#ffffff] border-2 border-[#1d1b16] px-3 py-1.5 rounded-lg shadow-brutal-sm text-xs font-mono font-bold text-[#666053] hover:text-[#1d1b16]">
          <span>Search</span>
          <kbd class="bg-[#f4f0e6] px-1.5 py-0.5 rounded border border-[#1d1b16] text-[10px] text-[#1d1b16]">/</kbd>
        </button>

        <!-- Shizuku Web Companion Button -->
        <a href="https://shizuku-web.onrender.com" target="_blank" class="posthog-btn-yellow px-3.5 py-1.5 sm:px-4 sm:py-2 rounded-xl text-xs sm:text-sm flex items-center gap-2">
          <span>⚡ Shizuku Web</span>
          <span class="bg-[#1d1b16] text-[#ffd000] text-[10px] px-1.5 py-0.2 rounded font-mono font-bold">LIVE</span>
        </a>

        <!-- GitHub Repo -->
        <a href="https://github.com/krishna3163/best_shizuku_apps_for_android_no_root" target="_blank" class="hidden sm:flex items-center gap-1.5 bg-[#ffffff] border-2 border-[#1d1b16] px-3 py-1.5 rounded-xl shadow-brutal-sm hover:shadow-brutal transition-all font-mono text-xs font-bold text-[#1d1b16]">
          <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"></path></svg>
          <span>Star</span>
        </a>
      </div>

    </div>
  </header>

  <!-- Hero Section -->
  <section class="pt-12 pb-8 px-4 sm:px-6 lg:px-8 max-w-7xl mx-auto w-full">
    <div class="bg-[#fff9d9] border-2 border-[#1d1b16] rounded-2xl p-6 sm:p-10 shadow-brutal-lg relative overflow-hidden">
      
      <!-- Top Pill -->
      <div class="inline-flex items-center gap-2 bg-[#ffd000] border-2 border-[#1d1b16] px-3 py-1 rounded-md text-xs font-mono font-bold shadow-brutal-sm mb-4">
        <span>⚡ 350+ VERIFIED NO-ROOT TOOLS</span>
      </div>

      <h1 class="text-3xl sm:text-5xl lg:text-6xl font-black tracking-tight text-[#1d1b16] leading-tight max-w-4xl">
        Superpowers for Android Apps <span class="bg-[#ffd000] px-2 rounded-lg inline-block">(Without Root)</span>
      </h1>

      <p class="text-base sm:text-lg text-[#524b3e] mt-4 max-w-3xl font-medium leading-relaxed">
        The ultimate searchable directory of apps, wireless ADB utilities, debloat scripts, and system modifiers powered by the <strong>Shizuku Binder API</strong>. Enjoy privileged Android features while keeping SafetyNet, Play Integrity, and banking apps 100% intact.
      </p>

      <!-- Stat Badges -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mt-8">
        <div class="bg-[#ffffff] border-2 border-[#1d1b16] p-4 rounded-xl shadow-brutal-sm">
          <div class="text-2xl sm:text-3xl font-black text-[#1d1b16] font-mono">350+</div>
          <div class="text-xs font-bold text-[#666053] uppercase mt-0.5">Verified Apps</div>
        </div>
        <div class="bg-[#ffffff] border-2 border-[#1d1b16] p-4 rounded-xl shadow-brutal-sm">
          <div class="text-2xl sm:text-3xl font-black text-[#22c55e] font-mono">100%</div>
          <div class="text-xs font-bold text-[#666053] uppercase mt-0.5">No Root Needed</div>
        </div>
        <div class="bg-[#ffffff] border-2 border-[#1d1b16] p-4 rounded-xl shadow-brutal-sm">
          <div class="text-2xl sm:text-3xl font-black text-[#f5a623] font-mono">31</div>
          <div class="text-xs font-bold text-[#666053] uppercase mt-0.5">Categories</div>
        </div>
        <div class="bg-[#ffffff] border-2 border-[#1d1b16] p-4 rounded-xl shadow-brutal-sm">
          <div class="text-2xl sm:text-3xl font-black text-[#1d1b16] font-mono">FOSS</div>
          <div class="text-xs font-bold text-[#666053] uppercase mt-0.5">Open Source</div>
        </div>
      </div>

    </div>
  </section>

  <!-- Main Content & Filters -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 w-full flex-1 pb-16">
    
    <!-- Controls Container -->
    <div id="controls" class="bg-[#ffffff] border-2 border-[#1d1b16] rounded-2xl p-5 sm:p-6 shadow-brutal mb-8">
      
      <!-- Search Input & Quick Action -->
      <div class="flex flex-col sm:flex-row gap-3 items-center">
        <div class="relative flex-1 w-full">
          <input 
            type="text" 
            id="searchInput" 
            placeholder="Search 350+ apps by name, description, license, or category... (Press '/' to focus)" 
            class="w-full bg-[#fcfaf6] border-2 border-[#1d1b16] rounded-xl px-4 py-3 pl-11 text-sm sm:text-base font-medium text-[#1d1b16] placeholder:text-[#8c8270] focus:outline-none focus:bg-[#ffffff] focus:shadow-brutal-sm transition-all"
          >
          <div class="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#666053]">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
          </div>
          <button id="clearBtn" class="hidden absolute right-3 top-1/2 -translate-y-1/2 bg-[#e2ded6] hover:bg-[#1d1b16] hover:text-white rounded-md w-6 h-6 items-center justify-center text-xs font-bold transition-colors">
            ✕
          </button>
        </div>

        <button onclick="toggleTopPicksOnly()" id="topPicksBtn" class="posthog-btn-white px-4 py-3 rounded-xl text-xs sm:text-sm font-bold flex items-center justify-center gap-2 w-full sm:w-auto flex-shrink-0">
          <span>⭐ Top Picks Only</span>
        </button>
      </div>

      <!-- Category Filter Pills -->
      <div class="mt-5 pt-4 border-t-2 border-[#f0ebe1]">
        <div class="flex items-center justify-between mb-2.5">
          <span class="text-xs font-mono font-bold text-[#666053] uppercase tracking-wider">Filter by Category:</span>
          <span id="activeFilterLabel" class="text-xs font-mono font-bold text-[#f5a623]">All Categories</span>
        </div>

        <div id="categoryPills" class="flex flex-wrap gap-2 max-h-36 overflow-y-auto pr-1 pb-1">
          <button onclick="selectCategory('All')" class="category-btn active-pill px-3 py-1 rounded-lg border-2 border-[#1d1b16] text-xs font-bold font-mono transition-all">
            All ({len(entries)})
          </button>
          <button onclick="selectCategory('Top Picks')" class="category-btn bg-[#ffffff] text-[#1d1b16] px-3 py-1 rounded-lg border-2 border-[#1d1b16] text-xs font-bold font-mono hover:bg-[#fff9d9] transition-all">
            ⭐ Top Picks ({categories_dict.get('Top Picks', 0)})
          </button>
'''

    # Add category buttons
    for cat in sorted_categories:
        if cat in ("Top Picks", "General"):
            continue
        count = categories_dict[cat]
        html_content += f'''          <button onclick="selectCategory('{escape(cat)}')" class="category-btn bg-[#ffffff] text-[#1d1b16] px-3 py-1 rounded-lg border-2 border-[#1d1b16] text-xs font-bold font-mono hover:bg-[#fff9d9] transition-all">
            {escape(cat)} ({count})
          </button>\n'''

    html_content += f'''        </div>
      </div>

      <!-- Live Counter & Active Filters Bar -->
      <div class="mt-4 pt-3 border-t border-[#f0ebe1] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs font-mono text-[#666053]">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-green-500"></span>
          <span id="counter" class="font-bold text-[#1d1b16]">Showing {len(entries)} of {len(entries)} apps</span>
        </div>
        <div class="flex items-center gap-3">
          <span>Sort: <strong>Curated / Featured First</strong></span>
          <span>•</span>
          <a href="#controls" onclick="resetFilters()" class="text-[#f5a623] hover:underline font-bold">Reset Filters</a>
        </div>
      </div>

    </div>

    <!-- App Cards Grid -->
    <div id="appsGrid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
'''

    # Generate cards
    for idx, app in enumerate(entries):
        clean_name = escape(app["name"])
        desc = escape(app["description"])
        license_str = escape(app["license"])
        cat_str = escape(app["category"])
        primary_url = escape(app["url"])
        is_featured = app["featured"]

        # Badges
        featured_badge = ''
        if is_featured:
            featured_badge = '<span class="bg-[#ffd000] text-[#1d1b16] border border-[#1d1b16] px-2 py-0.5 rounded text-[10px] font-mono font-black shadow-brutal-sm">⭐ TOP PICK</span>'

        # Link buttons
        links_html = ''
        for link in app["links"]:
            l_label = escape(link["label"])
            l_url = escape(link["url"])
            links_html += f'<a href="{l_url}" target="_blank" rel="noreferrer" class="bg-[#fcfaf6] hover:bg-[#ffd000] text-[#1d1b16] border-2 border-[#1d1b16] px-2.5 py-1 rounded-lg text-xs font-bold font-mono shadow-brutal-sm transition-all hover:-translate-y-0.5 flex items-center gap-1">{l_label} ↗</a>'

        html_content += f'''      <article 
        class="app-card bg-[#ffffff] border-2 border-[#1d1b16] rounded-xl p-5 shadow-brutal hover:shadow-brutal-hover hover:-translate-x-0.5 hover:-translate-y-0.5 transition-all flex flex-col justify-between"
        data-name="{clean_name.lower()}"
        data-desc="{desc.lower()}"
        data-cat="{cat_str.lower()}"
        data-license="{license_str.lower()}"
        data-featured="{str(is_featured).lower()}"
      >
        <div>
          <!-- Header -->
          <div class="flex items-start justify-between gap-2 mb-2">
            <h3 class="text-base sm:text-lg font-black text-[#1d1b16] tracking-tight leading-snug">
              <a href="{primary_url}" target="_blank" rel="noreferrer" class="hover:text-[#f5a623] hover:underline flex items-center gap-1.5">
                {clean_name}
              </a>
            </h3>
            <div class="flex items-center gap-1 flex-shrink-0">
              {featured_badge}
            </div>
          </div>

          <!-- Category & License Row -->
          <div class="flex flex-wrap items-center gap-1.5 mb-3 text-[11px] font-mono">
            <span class="bg-[#f4f0e6] text-[#423d33] border border-[#1d1b16] px-2 py-0.5 rounded-md font-semibold">
              📁 {cat_str}
            </span>
            <span class="bg-[#fff3b0] text-[#1d1b16] border border-[#1d1b16] px-2 py-0.5 rounded-md font-semibold">
              📜 {license_str}
            </span>
          </div>

          <!-- Description -->
          <p class="text-xs sm:text-sm text-[#423d33] leading-relaxed mb-4 font-normal">
            {desc}
          </p>
        </div>

        <!-- Footer / Action Links -->
        <div class="pt-3 border-t-2 border-[#f0ebe1] flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-1.5">
            {links_html}
          </div>
          <button onclick="copyAppLink('{clean_name}', '{primary_url}')" title="Copy project URL" class="text-[#666053] hover:text-[#1d1b16] p-1.5 rounded border border-transparent hover:border-[#1d1b16] hover:bg-[#f4f0e6] transition-colors">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>

      </article>\n'''

    html_content += f'''    </div>

    <!-- Empty State -->
    <div id="noResults" class="hidden bg-[#ffffff] border-2 border-[#1d1b16] rounded-2xl p-10 text-center shadow-brutal my-12">
      <div class="w-16 h-16 rounded-2xl bg-[#ffd000] border-2 border-[#1d1b16] shadow-brutal-sm mx-auto flex items-center justify-center text-2xl font-mono mb-4">
        🔍
      </div>
      <h3 class="text-xl font-black text-[#1d1b16]">No apps matched your query</h3>
      <p class="text-sm text-[#666053] mt-2 max-w-md mx-auto">
        Try adjusting your keywords or clearing the category filter. Or suggest a new Shizuku app to this repository!
      </p>
      <div class="mt-5 flex items-center justify-center gap-3">
        <button onclick="resetFilters()" class="posthog-btn-yellow px-4 py-2 rounded-xl text-xs font-mono">
          Clear Search & Filters
        </button>
        <a href="https://github.com/krishna3163/best_shizuku_apps_for_android_no_root/issues" target="_blank" class="posthog-btn-white px-4 py-2 rounded-xl text-xs font-mono">
          Suggest an App ↗
        </a>
      </div>
    </div>

  </main>

  <!-- Retro PostHog Footer -->
  <footer class="bg-[#ffffff] border-t-2 border-[#1d1b16] py-12 px-4 sm:px-6 lg:px-8 mt-auto">
    <div class="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
      
      <!-- Brand & Copy -->
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-[#ffd000] border-2 border-[#1d1b16] shadow-brutal-sm flex items-center justify-center font-bold text-xs">
          ⚡
        </div>
        <div>
          <span class="font-extrabold text-sm text-[#1d1b16]">Best Shizuku Apps Catalog</span>
          <p class="text-xs text-[#666053]">Curated community directory for no-root Android power users.</p>
        </div>
      </div>

      <!-- Links -->
      <div class="flex flex-wrap items-center gap-6 text-xs font-mono font-bold text-[#1d1b16]">
        <a href="https://shizuku-web.onrender.com" target="_blank" class="hover:text-[#f5a623] underline flex items-center gap-1">
          <span>Shizuku Web Companion</span>
          <span>↗</span>
        </a>
        <a href="https://shizuku.rikka.app" target="_blank" class="hover:text-[#f5a623] underline">
          Shizuku Official
        </a>
        <a href="https://github.com/krishna3163/best_shizuku_apps_for_android_no_root" target="_blank" class="hover:text-[#f5a623] underline">
          GitHub Repo
        </a>
        <a href="https://posthog.com" target="_blank" class="hover:text-[#f5a623] text-[#666053]">
          Design inspired by PostHog
        </a>
      </div>

    </div>
  </footer>

  <!-- Toast Notification -->
  <div id="toast" class="hidden fixed bottom-6 right-6 z-50 bg-[#1d1b16] text-[#ffffff] border-2 border-[#1d1b16] shadow-brutal p-4 rounded-xl items-center gap-3 text-xs font-mono">
    <div class="w-4 h-4 rounded-full bg-[#ffd000] text-[#1d1b16] flex items-center justify-center font-bold text-[10px]">✓</div>
    <span id="toastText">Copied to clipboard!</span>
  </div>

  <!-- Interactive JavaScript Engine -->
  <script>
    const searchInput = document.querySelector('#searchInput');
    const clearBtn = document.querySelector('#clearBtn');
    const counter = document.querySelector('#counter');
    const noResults = document.querySelector('#noResults');
    const appsGrid = document.querySelector('#appsGrid');
    const categoryPills = document.querySelectorAll('.category-btn');
    const activeFilterLabel = document.querySelector('#activeFilterLabel');
    const topPicksBtn = document.querySelector('#topPicksBtn');
    const cards = [...document.querySelectorAll('.app-card')];
    const toast = document.querySelector('#toast');
    const toastText = document.querySelector('#toastText');

    let currentCategory = 'All';
    let onlyTopPicks = false;

    function applyFilter() {{
      const query = searchInput.value.toLowerCase().trim();
      clearBtn.classList.toggle('hidden', query.length === 0);

      let visibleCount = 0;

      cards.forEach(card => {{
        const name = card.dataset.name || '';
        const desc = card.dataset.desc || '';
        const cat = card.dataset.cat || '';
        const license = card.dataset.license || '';
        const isFeatured = card.dataset.featured === 'true';

        const matchesQuery = query === '' || 
          name.includes(query) || 
          desc.includes(query) || 
          cat.includes(query) || 
          license.includes(query);

        const matchesCategory = currentCategory === 'All' || 
          (currentCategory === 'Top Picks' ? isFeatured : cat === currentCategory.toLowerCase());

        const matchesTopPicks = !onlyTopPicks || isFeatured;

        const isVisible = matchesQuery && matchesCategory && matchesTopPicks;
        card.style.display = isVisible ? 'flex' : 'none';
        if (isVisible) visibleCount++;
      }});

      counter.textContent = `Showing ${{visibleCount}} of ${{cards.length}} apps`;
      noResults.classList.toggle('hidden', visibleCount > 0);
      appsGrid.classList.toggle('hidden', visibleCount === 0);
    }}

    function selectCategory(category) {{
      currentCategory = category;
      categoryPills.forEach(btn => {{
        const isMatch = btn.textContent.trim().startsWith(category);
        btn.classList.toggle('active-pill', isMatch);
        btn.classList.toggle('bg-[#ffffff]', !isMatch);
      }});
      activeFilterLabel.textContent = category === 'All' ? 'All Categories' : category;
      applyFilter();
    }}

    function toggleTopPicksOnly() {{
      onlyTopPicks = !onlyTopPicks;
      topPicksBtn.classList.toggle('bg-[#ffd000]', onlyTopPicks);
      topPicksBtn.classList.toggle('bg-[#ffffff]', !onlyTopPicks);
      if (onlyTopPicks) {{
        triggerMascotConfetti();
      }}
      applyFilter();
    }}

    function resetFilters() {{
      searchInput.value = '';
      currentCategory = 'All';
      onlyTopPicks = false;
      topPicksBtn.classList.remove('bg-[#ffd000]');
      topPicksBtn.classList.add('bg-[#ffffff]');
      selectCategory('All');
      applyFilter();
    }}

    function focusSearch() {{
      searchInput.focus();
      searchInput.select();
    }}

    function triggerMascotConfetti() {{
      if (window.confetti) {{
        confetti({{
          particleCount: 50,
          spread: 60,
          origin: {{ y: 0.7 }},
          colors: ['#ffd000', '#f5a623', '#1d1b16', '#ffffff']
        }});
      }}
    }}

    function copyAppLink(name, url) {{
      navigator.clipboard.writeText(url);
      toastText.textContent = `Copied link for ${{name}}!`;
      toast.classList.remove('hidden');
      toast.classList.add('flex');
      setTimeout(() => {{
        toast.classList.add('hidden');
        toast.classList.remove('flex');
      }}, 2500);
    }}

    searchInput.addEventListener('input', applyFilter);
    clearBtn.addEventListener('click', () => {{
      searchInput.value = '';
      applyFilter();
      searchInput.focus();
    }});

    // Keyboard shortcut '/' to search
    window.addEventListener('keydown', (e) => {{
      if (e.key === '/' && document.activeElement !== searchInput) {{
        e.preventDefault();
        focusSearch();
      }}
      if (e.key === 'Escape' && document.activeElement === searchInput) {{
        searchInput.blur();
      }}
    }});

    // Initialize
    applyFilter();
  </script>

</body>
</html>
'''

    site_dir = ROOT / "site"
    site_dir.mkdir(exist_ok=True)
    (site_dir / "index.html").write_text(html_content, encoding="utf-8")
    print(f"Built {len(entries)} app cards with PostHog retro theme")

    try:
        from feed_generator import generate_feeds
        from fdroid_repo import build_fdroid_repository
        generate_feeds(site_dir)
        build_fdroid_repository(site_dir / "fdroid" / "repo", "https://krishna3163.github.io/best_shizuku_apps_for_android_no_root/fdroid/repo")
        print("Generated feeds (obtainium.json, releases.atom) and F-Droid repository index.")
    except Exception as exc:
        print(f"Notice: feed/fdroid generation: {exc}")

    try:
        from morphe_sync import update_all_morphe_pages
        morphe_releases_path = ROOT / "data" / "morphe-releases.json"
        morphe_status_path = ROOT / "data" / "morphe-status.json"
        morphe_config_path = ROOT / "config" / "morphe_apps.json"
        if morphe_releases_path.exists() and morphe_config_path.exists():
            with open(morphe_releases_path, "r", encoding="utf-8") as f:
                r_db = json.load(f)
            s_db = {}
            if morphe_status_path.exists():
                with open(morphe_status_path, "r", encoding="utf-8") as f:
                    s_db = json.load(f)
            with open(morphe_config_path, "r", encoding="utf-8") as f:
                c_apps = json.load(f).get("apps", [])
            update_all_morphe_pages(r_db, s_db, c_apps)
            print("Generated site/morphe.html and docs/MORPHE.md")
    except Exception as exc:
        print(f"Notice: morphe page generation: {exc}")


if __name__ == "__main__":
    build_html()