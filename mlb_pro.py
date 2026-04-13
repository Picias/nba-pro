import requests
import json
import time
import math
import os
import base64
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# ==========================================
# KONFIGURACJA GŁÓWNA
# ==========================================
GITHUB_TOKEN = os.environ.get('MY_GITHUB_TOKEN')
GITHUB_USERNAME = 'Picias'
GITHUB_REPO = 'nba-pro' 
TELEGRAM_TOKEN = os.environ.get('MY_TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = '5991219765'
ODDS_API_KEY = os.environ.get('MY_ODDS_API_KEY')

SPORT = 'baseball_mlb'
REGIONS = 'us'
MARKETS_PROPS = 'pitcher_strikeouts,batter_hits,batter_home_runs,batter_total_bases,batter_runs_scored,batter_rbis' 
MARKETS_GAMES = 'h2h,totals'

SEZON_MLB = 2026
DATA_DZIS = datetime.now().strftime('%Y-%m-%d')

MLB_JSON_FILE = 'mlb.json'
MLB_GAMES_FILE = 'mlb_games.json'
STATS_MLB_FILE = 'statystyki_mlb.json'

CACHE_PLAYER_LOGS = {}
CACHE_TEAM_K_RATE = {}
CACHE_TEAM_ERA = {}
CACHE_ROSTERS = {}
CACHE_PITCHER_STATS = {}
CACHE_BULLPEN_FATIGUE = {}
CACHE_TEAM_SPLITS = {}
CACHE_WEATHER = {}

LEAGUE_AVG_K_RATE = 0.225 
LEAGUE_AVG_ERA = 4.20
LEAGUE_AVG_BAA = 0.240 
LEAGUE_AVG_OPS = 0.730
LEAGUE_AVG_RUNS = 4.5
LEAGUE_AVG_RUNS_F5 = 2.5

MLB_TEAMS_LIST = [
    "Arizona Diamondbacks", "Atlanta Braves", "Baltimore Orioles", "Boston Red Sox",
    "Chicago Cubs", "Chicago White Sox", "Cincinnati Reds", "Cleveland Guardians",
    "Colorado Rockies", "Detroit Tigers", "Houston Astros", "Kansas City Royals",
    "Los Angeles Angels", "Los Angeles Dodgers", "Miami Marlins", "Milwaukee Brewers",
    "Minnesota Twins", "New York Mets", "New York Yankees", "Athletics", "Oakland Athletics",
    "Philadelphia Phillies", "Pittsburgh Pirates", "San Diego Padres", "San Francisco Giants",
    "Seattle Mariners", "St. Louis Cardinals", "Tampa Bay Rays", "Texas Rangers",
    "Toronto Blue Jays", "Washington Nationals"
]

PARK_FACTORS = {
    'Colorado Rockies': 1.15, 'Cincinnati Reds': 1.12, 'Boston Red Sox': 1.08,
    'Philadelphia Phillies': 1.05, 'Atlanta Braves': 1.05, 'Texas Rangers': 1.04,
    'Chicago White Sox': 1.03, 'Los Angeles Dodgers': 1.03, 'New York Yankees': 1.02,
    'Milwaukee Brewers': 1.01, 'Los Angeles Angels': 1.01, 'Washington Nationals': 1.01,
    'Chicago Cubs': 1.00, 'Toronto Blue Jays': 1.00, 'Arizona Diamondbacks': 0.99,
    'Kansas City Royals': 0.99, 'Houston Astros': 0.98, 'Minnesota Twins': 0.98,
    'Pittsburgh Pirates': 0.98, 'Detroit Tigers': 0.97, 'Baltimore Orioles': 0.96,
    'New York Mets': 0.96, 'Tampa Bay Rays': 0.96, 'Cleveland Guardians': 0.95,
    'St. Louis Cardinals': 0.95, 'Miami Marlins': 0.95, 'San Francisco Giants': 0.95,
    'Oakland Athletics': 0.94, 'San Diego Padres': 0.93, 'Seattle Mariners': 0.90
}

def get_park_factor(team_name):
    for t, pf in PARK_FACTORS.items():
        if t.lower() in team_name.lower() or team_name.lower() in t.lower(): return pf
    return 1.0

def wyslij_plik_na_githuba(file_path, wiadomosc_commit):
    url = f"https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{file_path}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    try:
        if not os.path.exists(file_path): return
        with open(file_path, "r", encoding="utf-8") as f: content = f.read()
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        sha = ""; res = requests.get(url, headers=headers)
        if res.status_code == 200: sha = res.json().get("sha", "")
        data = {"message": wiadomosc_commit, "content": encoded_content, "sha": sha}
        requests.put(url, headers=headers, json=data)
    except: pass

def poisson_prob_over(lam, line):
    if lam <= 0: return 0.0
    k_max = math.floor(line) 
    prob_under = 0.0
    for k in range(k_max + 1):
        prob_under += (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)
    return 1.0 - prob_under 

# ==========================================
# 🌤️ MODUŁ POGODY Z PRĘDKOŚCIĄ I KIERUNKIEM
# ==========================================
def pobierz_pogode_covers():
    print("🌤️ Pobieram dane pogodowe (Prędkość i Kierunek)...")
    weather_data = {}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    sources = [
        ("https://www.covers.com/sport/mlb/weather", "Covers"),
        ("https://www.rotowire.com/baseball/weather.php", "Rotowire")
    ]
    
    for url, src_name in sources:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200: continue
            
            soup = BeautifulSoup(res.text, 'html.parser')
            clean_text = soup.get_text(" ", strip=True).lower()
            
            znaleziono_dane = False
            for team in MLB_TEAMS_LIST:
                idx = clean_text.find(team.lower())
                if idx == -1: idx = clean_text.find(team.split()[-1].lower())
                    
                if idx != -1:
                    snippet = clean_text[max(0, idx-100) : min(len(clean_text), idx+250)]
                    
                    speed_match = re.search(r'(\d+(?:\.\d+)?)\s*mph', snippet)
                    speed_val = float(speed_match.group(1)) if speed_match else 0.0
                    speed_str = f"{speed_val} mph" if speed_val > 0 else ""
                    
                    w_mod = 1.0
                    msg = "🏟️ Zamknięty dach / Brak wpływu wiatru"
                    
                    if "dome" in snippet or "roof closed" in snippet:
                        w_mod = 1.0
                    elif speed_val > 0 or re.search(r'\b(out|in|left|right)\b', snippet):
                        kierunek = "Kierunek nieznany"
                        
                        if re.search(r'\b(blowing out|out to center)\b', snippet):
                            kierunek = "Wywiewa do Środka (W plecy ⬆️)"
                            w_mod = 1.08 if speed_val > 8 else 1.04
                        elif re.search(r'\b(blowing in|in from center)\b', snippet):
                            kierunek = "Wieje ze Środka (W twarz ⬇️)"
                            w_mod = 0.92 if speed_val > 8 else 0.96
                        elif re.search(r'\b(out to left|out to lf)\b', snippet):
                            kierunek = "Wywiewa na Lewe Zapole (↖️)"
                            w_mod = 1.05 if speed_val > 8 else 1.02
                        elif re.search(r'\b(out to right|out to rf)\b', snippet):
                            kierunek = "Wywiewa na Prawe Zapole (↗️)"
                            w_mod = 1.05 if speed_val > 8 else 1.02
                        elif re.search(r'\b(in from left|in from lf)\b', snippet):
                            kierunek = "Wieje z Lewego Zapola (↘️)"
                            w_mod = 0.96
                        elif re.search(r'\b(in from right|in from rf)\b', snippet):
                            kierunek = "Wieje z Prawego Zapola (↙️)"
                            w_mod = 0.96
                        elif re.search(r'\b(left to right|l to r)\b', snippet):
                            kierunek = "Z lewej na prawą (➡️)"
                            w_mod = 1.0
                        elif re.search(r'\b(right to left|r to l)\b', snippet):
                            kierunek = "Z prawej na lewą (⬅️)"
                            w_mod = 1.0
                            
                        if speed_str: msg = f"💨 Wiatr: {speed_str} | {kierunek}"
                        else: msg = f"💨 Wiatr: {kierunek}"

                    weather_data[team] = {'mod': w_mod, 'msg': msg}
                    znaleziono_dane = True
            
            if znaleziono_dane:
                print(f"  ✅ Poprawnie zaciągnięto wiatry (z prędkością) z: {src_name}")
                break 
        except: pass
        
    if not weather_data: print("  ⚠️ Brak danych o wietrze. Używam ustawień neutralnych.")
    global CACHE_WEATHER
    CACHE_WEATHER = weather_data
    return weather_data

def pobierz_ops_splits(team_id):
    if team_id in CACHE_TEAM_SPLITS: return CACHE_TEAM_SPLITS[team_id]
    ops_vs_lhp = LEAGUE_AVG_OPS; ops_vs_rhp = LEAGUE_AVG_OPS
    try:
        url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/stats?season={SEZON_MLB}&sportId=1&group=hitting&stats=statSplits&sitCodes=vl,vr"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        splits = res.get('stats', [{}])[0].get('splits', [])
        for s in splits:
            desc = s.get('split', {}).get('description', '').lower()
            ops = float(s.get('stat', {}).get('ops', str(LEAGUE_AVG_OPS)))
            if 'left' in desc: ops_vs_lhp = ops
            elif 'right' in desc: ops_vs_rhp = ops
    except: pass
    CACHE_TEAM_SPLITS[team_id] = {'vs_LHP': ops_vs_lhp, 'vs_RHP': ops_vs_rhp}
    return CACHE_TEAM_SPLITS[team_id]

def generuj_pelny_raport_druzynowy_mlb():
    plik_raportu = 'mlb_teams.json'
    if os.path.exists(plik_raportu):
        mod_time = datetime.fromtimestamp(os.path.getmtime(plik_raportu))
        if mod_time.strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d'): return 

    print("\n📊 Generowanie ZAAWANSOWANEGO raportu MLB (Statystyki drużynowe)...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    url_hit = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=hitting&stats=season&gameType=R"
    try:
        res_h = requests.get(url_hit, headers=headers, timeout=10).json()
        stats_h = res_h.get('stats', [])
        if not stats_h or not stats_h[0].get('splits'):
            res_h = requests.get(url_hit.replace(str(SEZON_MLB), str(SEZON_MLB - 1)), headers=headers, timeout=10).json()
            stats_h = res_h.get('stats', [])
    except: stats_h = []

    url_pitch = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=pitching&stats=season&gameType=R"
    try:
        res_p = requests.get(url_pitch, headers=headers, timeout=10).json()
        stats_p = res_p.get('stats', [])
        if not stats_p or not stats_p[0].get('splits'):
            res_p = requests.get(url_pitch.replace(str(SEZON_MLB), str(SEZON_MLB - 1)), headers=headers, timeout=10).json()
            stats_p = res_p.get('stats', [])
    except: stats_p = []

    druzyny_dane = {}
    if stats_h and stats_h[0].get('splits'):
        for t in stats_h[0]['splits']:
            t_name = t['team']['name']
            st = t['stat']
            druzyny_dane[t_name] = {
                "Zespol": t_name, "Mecze": st.get('gamesPlayed', 0), "Zdobyte_Runs": st.get('runs', 0),
                "Zdobyte_HR": st.get('homeRuns', 0), "Ofensywa_AVG": st.get('avg', '.000'), "Ofensywa_OPS": st.get('ops', '.000'),
                "Ofensywa_K": st.get('strikeOuts', 0), "Ofensywa_BB": st.get('baseOnBalls', 0)
            }
            
    if stats_p and stats_p[0].get('splits'):
        for t in stats_p[0]['splits']:
            t_name = t['team']['name']
            st = t['stat']
            if t_name not in druzyny_dane: continue
            era_str = st.get('era', '0.00'); era_str = '0.00' if era_str == '-.--' else era_str
            whip_str = st.get('whip', '0.00'); whip_str = '0.00' if whip_str == '-.--' else whip_str
            baa_str = st.get('avg', '.000'); baa_str = '.000' if baa_str == '.---' else baa_str
            druzyny_dane[t_name].update({
                "Obrona_ERA": era_str, "Obrona_WHIP": whip_str, "Obrona_BAA": baa_str,
                "Tracone_HR": st.get('homeRuns', 0), "Oddane_Walks": st.get('baseOnBalls', 0),
                "Miotacze_K": st.get('strikeOuts', 0), "Blown_Saves": st.get('blownSaves', 0), "Udane_Saves": st.get('saves', 0)
            })

    raport_finalny = list(druzyny_dane.values())
    if raport_finalny:
        raport_finalny = sorted(raport_finalny, key=lambda x: x['Zespol'])
        with open(plik_raportu, 'w', encoding='utf-8') as f: json.dump(raport_finalny, f, ensure_ascii=False, indent=4)
        wyslij_plik_na_githuba(plik_raportu, "Aktualizacja statystyk drużynowych MLB")
        
def rozlicz_wczorajsze_typy_mlb():
    try:
        with open(MLB_GAMES_FILE, 'r', encoding='utf-8') as f: stare_games = json.load(f)
    except: stare_games = []
    try:
        with open(MLB_JSON_FILE, 'r', encoding='utf-8') as f: stare_props = json.load(f)
    except: stare_props = []

    stare_typy = stare_games + stare_props
    if not stare_typy: return
    data_typow = stare_typy[0].get('data', '2000-01-01')
    if data_typow > DATA_DZIS: return
        
    print(f"\n🕵️ Uruchamiam Głównego Audytora MLB: Rozliczam typy z daty {data_typow}...")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_typow}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    rzeczywiste_staty = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if 'dates' not in res or not res['dates']: return
        mecze = res['dates'][0]['games']
        print(f"🔍 Audytor: Znalazłem {len(mecze)} meczów w terminarzu. Skanuję twarde Boxscore'y...")
        
        ukonczone_mecze = 0
        for m in mecze:
            away_t = m['teams']['away']['team']['name']; home_t = m['teams']['home']['team']['name']
            status_code = m['status']['statusCode']; game_id = m['gamePk']
            if status_code in ['F', 'O', 'C'] or m['status']['abstractGameState'] == 'Final': 
                ukonczone_mecze += 1
                try:
                    box_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore"
                    box_res = requests.get(box_url, headers=headers, timeout=5).json()
                    teams = box_res.get('teams', {})
                    for team_side in ['away', 'home']:
                        players = teams.get(team_side, {}).get('players', {})
                        for p_key, p_data in players.items():
                            name = p_data.get('person', {}).get('fullName', '').lower().replace(".", "").replace("'", "").strip()
                            if not name: continue
                            b_stats = p_data.get('stats', {}).get('batting', {}); p_stats = p_data.get('stats', {}).get('pitching', {})
                            rzeczywiste_staty[name] = {"K's": p_stats.get('strikeOuts', 0), 'Hits': b_stats.get('hits', 0), 'Home Runs': b_stats.get('homeRuns', 0), 'Total Bases': b_stats.get('totalBases', 0), 'Runs': b_stats.get('runs', 0), 'RBIs': b_stats.get('rbi', 0)}
                            
                    linescore = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game_id}/linescore", headers=headers).json()
                    innings = linescore.get('innings', [])
                    away_f5 = sum(i.get('away', {}).get('runs', 0) for i in innings[:5]); home_f5 = sum(i.get('home', {}).get('runs', 0) for i in innings[:5])
                    away_fg = m['teams']['away'].get('score', 0); home_fg = m['teams']['home'].get('score', 0)
                    m_key = f"{away_t} @ {home_t}".lower()
                    
                    rzeczywiste_staty[m_key] = {
                        'Mecz: Suma Runs': away_fg + home_fg,
                        'Mecz: Zwycięzca (ML)': home_t if home_fg > away_fg else away_t,
                        'F5: Drużyna powyżej 1.5 Runs': away_f5 if "OVER" in away_t else home_f5 
                    }
                except Exception as box_err: pass
        if ukonczone_mecze == 0: return
    except Exception as e: return
            
    wygrane = przegrane = zwroty = profit = 0
    historia = []
    
    for typ in stare_typy:
        rynek = typ['rynek']; linia = typ.get('linia', 0); zaw = typ.get('zawodnik', typ.get('zaklad', '')).lower().replace(".", "").replace("'", "").strip()
        mecz_key = typ.get('mecz', '').lower()
        is_game_line = "Mecz:" in rynek or "F5" in rynek
        search_key = mecz_key if is_game_line else zaw
        znaleziony_zaw = next((k for k in rzeczywiste_staty.keys() if search_key in k or k in search_key), None)
        
        if not znaleziony_zaw:
            historia.append({"zawodnik": typ.get('zawodnik', typ.get('zaklad', 'Mecz')), "rynek": rynek, "status": "ZWROT", "kategoria": "Zwykły Typ"})
            zwroty += 1; continue
            
        wynik = rzeczywiste_staty[znaleziony_zaw].get(rynek, 0); zaklad = str(typ.get('zaklad', typ.get('typ', '')))
        
        if "F5: Drużyna" in rynek:
            team_name = zaklad.replace(" OVER", "").replace(" UNDER", "").strip()
            f5_runs = rzeczywiste_staty[mecz_key].get('away_f5') if team_name.lower() in mecz_key.split('@')[0] else rzeczywiste_staty[mecz_key].get('home_f5', 0)
            czy_weszlo = (f5_runs > 1.5) if "OVER" in zaklad else (f5_runs < 1.5)
            wynik = f5_runs
        elif "Zwycięzca" in rynek or "ML" in rynek:
            if wynik == "REMIS": czy_weszlo = None
            else: czy_weszlo = (zaklad.lower() == str(wynik).lower())
        else:
            if wynik == linia: czy_weszlo = None
            else: czy_weszlo = ("OVER" in zaklad and wynik > float(linia)) or ("UNDER" in zaklad and wynik < float(linia))
        
        if czy_weszlo is None: zwroty += 1; status = "➖ ZWROT"
        elif czy_weszlo: wygrane += 1; profit += (typ.get('kurs', 1.0) - 1.0); status = "✅ WYGRANA"
        else: przegrane += 1; profit -= 1.0; status = "❌ PRZEGRANA"
            
        is_value = typ.get('is_value', False); is_safe = typ.get('is_safe', False); is_stable = typ.get('is_stable', False); is_graal = typ.get('is_graal', False)
        etykiety = []
        if is_game_line: etykiety.append("📊 Typ Meczowy")
        else:
            if is_graal: etykiety.append("🏆 Graal")
            else:
                if is_value: etykiety.append("💰 Value")
                if is_safe: etykiety.append("🎯 Pewniak")
                if is_stable: etykiety.append("🛡️ Stabilny")
            
        historia.append({"zawodnik": typ.get('zawodnik', typ.get('zaklad', 'Mecz')), "rynek": rynek, "typ": zaklad, "linia": linia, "kurs": typ.get('kurs', 0.0), "wynik_realny": wynik, "status": status, "kategoria": " | ".join(etykiety) if etykiety else "Zwykły Typ"})
            
    suma = wygrane + przegrane
    if suma > 0:
        hit_rate = round((wygrane / suma) * 100, 1); roi = round((profit / suma) * 100, 1)
        try:
            with open(STATS_MLB_FILE, 'r', encoding='utf-8') as f: baza_stat = json.load(f)
        except: baza_stat = []
        baza_stat = [r for r in baza_stat if r['data_meczow'] != data_typow]
        baza_stat.insert(0, {"data_meczow": data_typow, "wygrane": wygrane, "przegrane": przegrane, "zwroty": zwroty, "hit_rate": f"{hit_rate}%", "profit_jednostki": round(profit, 2), "roi": f"{roi}%", "detale": historia})
        with open(STATS_MLB_FILE, 'w', encoding='utf-8') as f: json.dump(baza_stat, f, ensure_ascii=False, indent=4)
        wyslij_plik_na_githuba(STATS_MLB_FILE, f"Auto-Raport MLB ({data_typow})")

def pobierz_oficjalny_terminarz_mlb(data_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_str}&hydrate=probablePitcher,lineups"
    baza_mlb = {}
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
        if 'dates' in res and len(res['dates']) > 0:
            for m in res['dates'][0]['games']:
                home_team = m['teams']['home']['team']['name']
                away_team = m['teams']['away']['team']['name']
                home_p = m['teams']['home'].get('probablePitcher', {})
                away_p = m['teams']['away'].get('probablePitcher', {})
                
                klucz_meczu = f"{away_team} @ {home_team}".lower().replace("st. ", "st ")
                baza_mlb[klucz_meczu] = {
                    'home_team': home_team, 'home_team_id': m['teams']['home']['team']['id'], 
                    'away_team': away_team, 'away_team_id': m['teams']['away']['team']['id'],
                    'home_pitcher': home_p.get('fullName', 'TBD'), 'home_pitcher_id': home_p.get('id', None),
                    'away_pitcher': away_p.get('fullName', 'TBD'), 'away_pitcher_id': away_p.get('id', None)
                }
    except: pass
    return baza_mlb

def pobierz_staty_miotacza_startowego(pitcher_id):
    if not pitcher_id: return {'era': LEAGUE_AVG_ERA, 'baa': LEAGUE_AVG_BAA, 'hand': 'R'}
    if pitcher_id in CACHE_PITCHER_STATS: return CACHE_PITCHER_STATS[pitcher_id]
    
    era = LEAGUE_AVG_ERA
    baa = LEAGUE_AVG_BAA
    hand = 'R'
    
    try:
        url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}?hydrate=stats(group=[pitching],type=[season],season={SEZON_MLB})"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        if 'people' in res and len(res['people']) > 0:
            p_data = res['people'][0]
            hand = p_data.get('pitchHand', {}).get('code', 'R') 
            stats = p_data.get('stats', [])
            if not stats: 
                url_prev = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}?hydrate=stats(group=[pitching],type=[season],season={SEZON_MLB-1})"
                res_prev = requests.get(url_prev, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
                if 'people' in res_prev and len(res_prev['people']) > 0:
                    stats = res_prev['people'][0].get('stats', [])
            if stats and stats[0].get('splits'):
                stat_obj = stats[0]['splits'][0]['stat']
                era_str = stat_obj.get('era', str(LEAGUE_AVG_ERA))
                if era_str == '-.--': era_str = str(LEAGUE_AVG_ERA)
                era = float(era_str)
                avg_str = stat_obj.get('avg', '.240')
                if avg_str == '.---': avg_str = '.240'
                baa = float(avg_str) if avg_str.startswith('.') else LEAGUE_AVG_BAA
    except: pass
    
    if era < 1.50: era = LEAGUE_AVG_ERA
    
    CACHE_PITCHER_STATS[pitcher_id] = {'era': era, 'baa': baa, 'hand': hand}
    return CACHE_PITCHER_STATS[pitcher_id]

def oblicz_zmeczenie_bullpenu(team_id, data_dzis_str):
    if team_id in CACHE_BULLPEN_FATIGUE: return CACHE_BULLPEN_FATIGUE[team_id]
    dzis = datetime.strptime(data_dzis_str, '%Y-%m-%d')
    start_date = (dzis - timedelta(days=3)).strftime('%Y-%m-%d')
    end_date = (dzis - timedelta(days=1)).strftime('%Y-%m-%d')
    
    rozegrane_mecze = 0
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&startDate={start_date}&endDate={end_date}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        for d in res.get('dates', []):
            for g in d.get('games', []):
                if g['status']['statusCode'] in ['F', 'O', 'C']: rozegrane_mecze += 1
    except: pass

    if rozegrane_mecze >= 4: bonus = 1.08; msg = "🥵 BP Zajechany (+8%)"
    elif rozegrane_mecze == 3: bonus = 1.04; msg = "🥱 BP Zmęczony (+4%)"
    elif rozegrane_mecze <= 1: bonus = 0.97; msg = "🔋 BP Wypoczęty (-3%)"
    else: bonus = 1.0; msg = "BP Gotowy"
        
    CACHE_BULLPEN_FATIGUE[team_id] = {'korekta': bonus, 'uwaga': msg}
    return CACHE_BULLPEN_FATIGUE[team_id]

def pobierz_historie_gracza(player_id, typ_gracza, stat_key):
    if not player_id: return []
    cache_key = f"{player_id}_{stat_key}"
    if cache_key in CACHE_PLAYER_LOGS: return CACHE_PLAYER_LOGS[cache_key]
    
    time.sleep(0.05) 
    group = "pitching" if typ_gracza == "pitcher" else "hitting"
    historia_pelna = []
    
    for s in [SEZON_MLB, SEZON_MLB - 1]:
        try:
            url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={s}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
            if 'stats' in res and len(res['stats']) > 0:
                splits = res['stats'][0].get('splits', [])
                for game in reversed(splits):
                    st = game.get('stat', {})
                    if typ_gracza == "pitcher" and float(st.get('inningsPitched', '0')) < 3.0: continue
                    if typ_gracza == "batter" and st.get('atBats', 0) < 2: continue
                    historia_pelna.append({'val': st.get(stat_key if typ_gracza == "batter" else 'strikeOuts', 0), 'isHome': game.get('isHome', False)})
                    if len(historia_pelna) >= 15: break
        except: pass
        if len(historia_pelna) >= 15: break

    historia_pelna.reverse() 
    CACHE_PLAYER_LOGS[cache_key] = historia_pelna
    return historia_pelna

def pobierz_statystyki_druzyn_mlb():
    global LEAGUE_AVG_K_RATE, LEAGUE_AVG_ERA
    print("📊 Pobieram uśrednione statystyki ligowe (K-Rate i Team ERA)...")
    try:
        res_p = requests.get(f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=pitching&stats=season&gameType=R", headers={'User-Agent': 'Mozilla/5.0'}, timeout=10).json()
        stats_p = res_p.get('stats', [])
        if stats_p and stats_p[0].get('splits'):
            total_era = 0; count = 0
            for team in stats_p[0]['splits']:
                era_str = team['stat'].get('era', str(LEAGUE_AVG_ERA))
                era = float(era_str) if era_str != '-.--' else LEAGUE_AVG_ERA
                total_era += era; count += 1
            if count > 0: LEAGUE_AVG_ERA = total_era / count
    except: pass

# ==========================================
# 3. GŁÓWNA PĘTLA BOTA (GAME LINES & PROPS)
# ==========================================
def uruchom_mlb_pro():
    print("==================================================")
    print("🚀 QUANT AI BOTS: MLB PRO ULTIMATE v8.1 (Wind Direction + Speed)")
    print("==================================================")
    
    if not os.path.exists(STATS_MLB_FILE):
        with open(STATS_MLB_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
        wyslij_plik_na_githuba(STATS_MLB_FILE, "Inicjalizacja pustego pliku")
    
    rozlicz_wczorajsze_typy_mlb()
    pobierz_statystyki_druzyn_mlb()
    generuj_pelny_raport_druzynowy_mlb() 
    pobierz_pogode_covers()
    baza_mlb = pobierz_oficjalny_terminarz_mlb(DATA_DZIS)
    
    try:
        print("📡 Pobieram listę zdarzeń z The Odds API...")
        events = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={ODDS_API_KEY}&regions={REGIONS}").json()
        if isinstance(events, dict) and 'message' in events: 
            print(f"❌ BŁĄD THE ODDS API: {events['message']}")
            return []
    except Exception as e: 
        print(f"❌ BŁĄD POŁĄCZENIA Z API KURSÓW: {e}")
        return []

    if not isinstance(events, list): return []
    mecze_dzis = [e for e in events if (datetime.strptime(e['commence_time'], '%Y-%m-%dT%H:%M:%SZ') - timedelta(hours=5)).strftime('%Y-%m-%d') == DATA_DZIS]
    
    wyniki_props = []
    wyniki_games = []
    przetworzeni_zawodnicy = set()

    rynek_map = {
        'pitcher_strikeouts': ('K\'s', 'pitcher', 'strikeOuts'),
        'batter_hits': ('Hits', 'batter', 'hits'),
        'batter_home_runs': ('Home Runs', 'batter', 'homeRuns'),
        'batter_total_bases': ('Total Bases', 'batter', 'totalBases'),
        'batter_runs_scored': ('Runs', 'batter', 'runs'),
        'batter_rbis': ('RBIs', 'batter', 'rbi')
    }

    for ev in mecze_dzis:
        m_str = f"{ev['away_team']} @ {ev['home_team']}"
        dane_oficjalne = baza_mlb.get(m_str.lower().replace("st. ", "st "), {})
        if not dane_oficjalne: continue
        
        print(f"\n🏟️ ------------------------------------------------")
        print(f"⚾ ANALIZA MECZU: {m_str}")
        
        home_t_id = dane_oficjalne['home_team_id']
        away_t_id = dane_oficjalne['away_team_id']
        
        # Wyłapujemy dokładną pogodę przypisaną do domowej drużyny z cache
        w_data = next((v for k, v in CACHE_WEATHER.items() if k.lower() in ev['home_team'].lower() or ev['home_team'].lower() in k.lower()), {'mod': 1.0, 'msg': 'Neutralnie / Dach'})
        p_factor = get_park_factor(ev['home_team'])
        
        away_ops_splits = pobierz_ops_splits(away_t_id)
        home_ops_splits = pobierz_ops_splits(home_t_id)
        
        home_p_stats = pobierz_staty_miotacza_startowego(dane_oficjalne.get('home_pitcher_id'))
        away_p_stats = pobierz_staty_miotacza_startowego(dane_oficjalne.get('away_pitcher_id'))
        
        home_p_hand = home_p_stats['hand']
        away_p_hand = away_p_stats['hand']
        
        home_bp = oblicz_zmeczenie_bullpenu(home_t_id, DATA_DZIS)
        away_bp = oblicz_zmeczenie_bullpenu(away_t_id, DATA_DZIS)

        away_pitcher_mod = max(0.6, min(1.5, home_p_stats['era'] / LEAGUE_AVG_ERA))
        home_pitcher_mod = max(0.6, min(1.5, away_p_stats['era'] / LEAGUE_AVG_ERA))

        away_ops_vs_sp = away_ops_splits['vs_LHP'] if home_p_hand == 'L' else away_ops_splits['vs_RHP']
        away_ops_vs_bp = (away_ops_splits['vs_LHP'] + away_ops_splits['vs_RHP']) / 2.0
        away_true_ops_full = (away_ops_vs_sp * 0.65) + (away_ops_vs_bp * 0.35)
        away_base_runs_fg = (away_true_ops_full / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS
        away_proj_runs_fg = away_base_runs_fg * away_pitcher_mod * home_bp['korekta'] * p_factor * w_data['mod']
        
        home_ops_vs_sp = home_ops_splits['vs_LHP'] if away_p_hand == 'L' else home_ops_splits['vs_RHP']
        home_ops_vs_bp = (home_ops_splits['vs_LHP'] + home_ops_splits['vs_RHP']) / 2.0
        home_true_ops_full = (home_ops_vs_sp * 0.65) + (home_ops_vs_bp * 0.35)
        home_base_runs_fg = (home_true_ops_full / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS
        home_proj_runs_fg = home_base_runs_fg * home_pitcher_mod * away_bp['korekta'] * p_factor * w_data['mod'] * 1.04 
        
        total_proj_runs_fg = round(away_proj_runs_fg + home_proj_runs_fg, 2)
        try: home_win_prob_fg = (home_proj_runs_fg**1.83) / (home_proj_runs_fg**1.83 + away_proj_runs_fg**1.83)
        except: home_win_prob_fg = 0.5

        away_base_runs_f5 = (away_ops_vs_sp / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS_F5
        away_proj_runs_f5 = away_base_runs_f5 * away_pitcher_mod * p_factor * w_data['mod']
        home_base_runs_f5 = (home_ops_vs_sp / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS_F5
        home_proj_runs_f5 = home_base_runs_f5 * home_pitcher_mod * p_factor * w_data['mod'] * 1.04
        
        total_proj_runs_f5 = round(away_proj_runs_f5 + home_proj_runs_f5, 2)

        print(f"  📈 Kalkulator Mecz: {ev['away_team']} {round(away_proj_runs_fg, 1)} - {round(home_proj_runs_fg, 1)} {ev['home_team']} (Suma: {total_proj_runs_fg})")
        print(f"  ⏱️ Kalkulator F5: {ev['away_team']} {round(away_proj_runs_f5, 1)} - {round(home_proj_runs_f5, 1)} {ev['home_team']} (Suma: {total_proj_runs_f5})")

        g_insights = f"🌦️ {w_data['msg']} | 🏟️ Park: {p_factor}x<br>"
        g_insights += f"⚾ <b>{ev['home_team']}</b> vs {away_p_hand}HP: OPS {round(home_ops_vs_sp,3)} | SP ERA: {round(home_p_stats['era'],2)} | {home_bp['uwaga']}<br>"
        g_insights += f"⚾ <b>{ev['away_team']}</b> vs {home_p_hand}HP: OPS {round(away_ops_vs_sp,3)} | SP ERA: {round(away_p_stats['era'],2)} | {away_bp['uwaga']}"

        print(f"    📡 Odpytuję API o linie meczowe...")
        game_lines = {'h2h': {}, 'totals': {}}
        try:
            time.sleep(0.5) 
            res_games = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS_GAMES}&oddsFormat=decimal").json()
            for bm in res_games.get('bookmakers', []):
                for mkt in bm.get('markets', []):
                    if mkt['key'] == 'h2h':
                        for oc in mkt['outcomes']: game_lines['h2h'][oc['name']] = oc['price']
                    elif mkt['key'] == 'totals':
                        for oc in mkt['outcomes']: 
                            if oc.get('description'): continue 
                            if oc.get('point', 0) < 5.0: continue 
                            game_lines['totals']['point'] = oc['point']
                            game_lines['totals'][oc['name']] = oc['price']
        except Exception as e: pass

        if game_lines['totals'] and 'Over' in game_lines['totals']:
            t_line = game_lines['totals']['point']
            t_over = game_lines['totals']['Over']
            t_under = game_lines['totals']['Under']
            
            prob_over = poisson_prob_over(total_proj_runs_fg, t_line)
            prob_under = 1.0 - prob_over
            ev_o = (prob_over * t_over) - 1; ev_u = (prob_under * t_under) - 1
            
            print(f"    🎲 Mecz Totals {t_line} | OVER: {round(prob_over*100,1)}% (EV: {round(ev_o*100,1)}%) | UNDER: {round(prob_under*100,1)}% (EV: {round(ev_u*100,1)}%)")
            if ev_o > 0.02: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Suma Runs", "zaklad": "OVER", "linia": t_line, "kurs": t_over, "projekcja": total_proj_runs_fg, "szansa": round(prob_over * 100, 1), "ev": round(ev_o, 3), "uwagi": g_insights})
            elif ev_u > 0.02: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Suma Runs", "zaklad": "UNDER", "linia": t_line, "kurs": t_under, "projekcja": total_proj_runs_fg, "szansa": round(prob_under * 100, 1), "ev": round(ev_u, 3), "uwagi": g_insights})

        if game_lines['h2h'] and ev['home_team'] in game_lines['h2h']:
            h_kurs = game_lines['h2h'][ev['home_team']]
            a_kurs = game_lines['h2h'][ev['away_team']]
            ev_h = (home_win_prob_fg * h_kurs) - 1; ev_a = ((1-home_win_prob_fg) * a_kurs) - 1
            
            print(f"    ⚔️ Mecz ML Home: {round(home_win_prob_fg*100,1)}% (EV: {round(ev_h*100,1)}%) | ML Away: {round((1-home_win_prob_fg)*100,1)}% (EV: {round(ev_a*100,1)}%)")
            if ev_h > 0.02: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Zwycięzca (ML)", "zaklad": ev['home_team'], "linia": "-", "kurs": h_kurs, "projekcja": f"{round(home_proj_runs_fg,1)} - {round(away_proj_runs_fg,1)}", "szansa": round(home_win_prob_fg * 100, 1), "ev": round(ev_h, 3), "uwagi": g_insights})
            elif ev_a > 0.02: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Zwycięzca (ML)", "zaklad": ev['away_team'], "linia": "-", "kurs": a_kurs, "projekcja": f"{round(away_proj_runs_fg,1)} - {round(home_proj_runs_fg,1)}", "szansa": round((1-home_win_prob_fg) * 100, 1), "ev": round(ev_a, 3), "uwagi": g_insights})

        prob_away_f5_under_1_5 = (math.pow(away_proj_runs_f5, 0) * math.exp(-away_proj_runs_f5)) / math.factorial(0) + (math.pow(away_proj_runs_f5, 1) * math.exp(-away_proj_runs_f5)) / math.factorial(1)
        prob_away_f5_over_1_5 = 1.0 - prob_away_f5_under_1_5
        prob_home_f5_under_1_5 = (math.pow(home_proj_runs_f5, 0) * math.exp(-home_proj_runs_f5)) / math.factorial(0) + (math.pow(home_proj_runs_f5, 1) * math.exp(-home_proj_runs_f5)) / math.factorial(1)
        prob_home_f5_over_1_5 = 1.0 - prob_home_f5_under_1_5

        if prob_away_f5_over_1_5 > 0.60:
            fair_odds_a = 1 / prob_away_f5_over_1_5
            print(f"    🎯 F5 Team Totals OVER 1.5: {ev['away_team']} | Szansa: {round(prob_away_f5_over_1_5*100,1)}% | FAIR KURS: {round(fair_odds_a,2)}")
            wyniki_games.append({
                "mecz": m_str, "data": DATA_DZIS, "rynek": "F5: Drużyna powyżej 1.5 Runs", "zaklad": f"{ev['away_team']} OVER", 
                "linia": 1.5, "kurs": round(fair_odds_a, 2), "projekcja": round(away_proj_runs_f5, 2), 
                "szansa": round(prob_away_f5_over_1_5 * 100, 1), "ev": 0.1, 
                "uwagi": g_insights + f"<br><br>🎯 <b>Szukaj u bukmachera kursu > {round(fair_odds_a + 0.05, 2)} na OVER 1.5 Runs do 5. inningu!</b>"
            })
            
        if prob_home_f5_over_1_5 > 0.60:
            fair_odds_h = 1 / prob_home_f5_over_1_5
            print(f"    🎯 F5 Team Totals OVER 1.5: {ev['home_team']} | Szansa: {round(prob_home_f5_over_1_5*100,1)}% | FAIR KURS: {round(fair_odds_h,2)}")
            wyniki_games.append({
                "mecz": m_str, "data": DATA_DZIS, "rynek": "F5: Drużyna powyżej 1.5 Runs", "zaklad": f"{ev['home_team']} OVER", 
                "linia": 1.5, "kurs": round(fair_odds_h, 2), "projekcja": round(home_proj_runs_f5, 2), 
                "szansa": round(prob_home_f5_over_1_5 * 100, 1), "ev": 0.1, 
                "uwagi": g_insights + f"<br><br>🎯 <b>Szukaj u bukmachera kursu > {round(fair_odds_h + 0.05, 2)} na OVER 1.5 Runs do 5. inningu!</b>"
            })

        print(f"    🏃 Odpytuję API o zawodników...")
        try:
            time.sleep(0.5) 
            res_props = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS_PROPS}&oddsFormat=decimal").json()
        except: continue
        
        h_roster = {}
        a_roster = {}
        try:
            res_h = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['home_team_id']}/roster?hydrate=person", timeout=10).json()
            h_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_h.get('roster', [])}
            res_a = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['away_team_id']}/roster?hydrate=person", timeout=10).json()
            a_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_a.get('roster', [])}
        except: pass

        for bm in res_props.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                if mkt['key'] not in rynek_map: continue
                nazwa_rynku_pl, rola, mlb_stat_key = rynek_map[mkt['key']]
                
                player_odds = {}
                for oc in mkt['outcomes']:
                    p_name = oc['description']
                    if p_name not in player_odds: 
                        player_odds[p_name] = {'Over': 1.85, 'Under': 1.85, 'point': oc.get('point', 0.5)}
                    player_odds[p_name][oc['name']] = oc['price']
                
                for p_name, d_odds in player_odds.items():
                    linia = d_odds['point']
                    kurs_over = d_odds['Over']
                    kurs_under = d_odds['Under']
                    
                    if mlb_stat_key == 'totalBases': linia = 1.5
                    elif mlb_stat_key == 'hits': linia = 0.5
                    
                    if f"{p_name}_{mkt['key']}" in przetworzeni_zawodnicy: continue
                    przetworzeni_zawodnicy.add(f"{p_name}_{mkt['key']}")
                    
                    player_id = None; is_today_home = False; opp_team_id = None; opp_name = ""; bat_side = 'R'; b_order = 0
                    
                    if rola == 'pitcher':
                        h_clean = dane_oficjalne.get('home_pitcher', '').lower().replace(".", "").strip()
                        a_clean = dane_oficjalne.get('away_pitcher', '').lower().replace(".", "").strip()
                        p_clean = p_name.lower().replace(".", "").strip()
                        
                        if p_clean in h_clean or h_clean in p_clean: 
                            player_id = dane_oficjalne.get('home_pitcher_id')
                            is_today_home = True
                            opp_team_id = dane_oficjalne['away_team_id']
                            opp_name = ev['away_team']
                        elif p_clean in a_clean or a_clean in p_clean: 
                            player_id = dane_oficjalne.get('away_pitcher_id')
                            is_today_home = False
                            opp_team_id = dane_oficjalne['home_team_id']
                            opp_name = ev['home_team']
                    else:
                        p_clean = p_name.lower().replace(".", "").strip()
                        if p_clean in h_roster:
                            player_id = h_roster[p_clean]['id']
                            bat_side = h_roster[p_clean].get('batSide', {}).get('code', 'R')
                            is_today_home = True
                            opp_team_id = dane_oficjalne['away_team_id']
                            opp_name = ev['away_team']
                            b_order = dane_oficjalne.get('lineups_home', {}).get(player_id, 0)
                        elif p_clean in a_roster:
                            player_id = a_roster[p_clean]['id']
                            bat_side = a_roster[p_clean].get('batSide', {}).get('code', 'R')
                            is_today_home = False
                            opp_team_id = dane_oficjalne['home_team_id']
                            opp_name = ev['home_team']
                            b_order = dane_oficjalne.get('lineups_away', {}).get(player_id, 0)
                    
                    if not player_id: continue
                    hist_data = pobierz_historie_gracza(player_id, rola, mlb_stat_key)
                    if len(hist_data) < 5: continue
                    
                    vals = [h['val'] for h in hist_data[-15:]]
                    weights = [3 if i >= len(vals)-5 else (2 if i >= len(vals)-10 else 1) for i in range(len(vals))]
                    baza_proj = sum(v * w for v, w in zip(vals, weights)) / sum(weights)
                    
                    split_bonus = 1.0
                    h_vals = [h['val'] for h in hist_data if h['isHome']]
                    a_vals = [h['val'] for h in hist_data if not h['isHome']]
                    if is_today_home and h_vals and a_vals:
                        if sum(h_vals)/len(h_vals) > (sum(a_vals)/len(a_vals)) * 1.1: split_bonus = 1.07
                    elif not is_today_home and a_vals and h_vals:
                        if sum(a_vals)/len(a_vals) > (sum(h_vals)/len(h_vals)) * 1.1: split_bonus = 1.07
                    
                    korekta = split_bonus
                    uwagi = f"🔥 WMA: {round(baza_proj,2)}."
                    m_color = "rank-yellow"; m_rank = "Neutral"
                    
                    p_hand = away_p_hand if is_today_home else home_p_hand
                    
                    if rola == 'pitcher':
                        opp_k_rate = CACHE_TEAM_K_RATE.get(opp_team_id, LEAGUE_AVG_K_RATE)
                        korekta *= max(0.85, min(1.15, opp_k_rate / LEAGUE_AVG_K_RATE))
                        m_color = "rank-green" if korekta > 1.05 else "rank-red"
                        m_rank = f"K-Rate rywala: {round(opp_k_rate*100,1)}%"
                    else:
                        opp_pitcher_id = dane_oficjalne.get('away_pitcher_id') if is_today_home else dane_oficjalne.get('home_pitcher_id')
                        opp_pitcher_name = dane_oficjalne.get('away_pitcher', 'TBD') if is_today_home else dane_oficjalne.get('home_pitcher', 'TBD')
                        
                        p_stats = pobierz_staty_miotacza_startowego(opp_pitcher_id)
                        baa_korekta = max(0.85, min(1.15, p_stats['baa'] / LEAGUE_AVG_BAA))
                        
                        if baa_korekta >= 1.05: m_color = "rank-green"; m_rank = "Słaby Miotacz"
                        elif baa_korekta <= 0.95: m_color = "rank-red"; m_rank = "Elitarny Miotacz"
                        
                        opp_era = CACHE_TEAM_ERA.get(opp_team_id, LEAGUE_AVG_ERA)
                        era_korekta = max(0.90, min(1.10, opp_era / LEAGUE_AVG_ERA))
                        
                        bullpen = oblicz_zmeczenie_bullpenu(opp_team_id, DATA_DZIS)
                        
                        korekta *= (baa_korekta * era_korekta * bullpen['korekta'])
                        
                        uwagi += f" ⚾ SP: {opp_pitcher_name} (ERA: {round(p_stats['era'], 2)}, BAA: {str(p_stats['baa']).lstrip('0')})."
                        uwagi += f" 🛡️ BP ERA: {round(opp_era, 2)}."
                        if bullpen['uwaga']: uwagi += f" {bullpen['uwaga']}"
                        
                        pf = get_park_factor(ev['home_team'])
                        if mlb_stat_key == 'homeRuns': pf = ((pf - 1.0) * 1.5) + 1.0 
                        if pf != 1.0: 
                            korekta *= pf
                            uwagi += f" 🏟️ Stadion PF: {round(pf, 2)}x."
                        
                        # --- FIX: Inteligentna zagnieżdżona pogoda ---
                        w_mod_raw = w_data['mod']
                        w_msg_short = w_data['msg'].replace("💨 Wiatr: ", "").replace("💨 ", "")
                        
                        if w_mod_raw != 1.0:
                            if rola == 'pitcher':
                                p_weather_mod = 1.0 - (w_mod_raw - 1.0) * 0.5 
                                korekta *= p_weather_mod
                                if w_mod_raw > 1.0: uwagi += f" 🌦️ Wiatr {w_msg_short} (Ostrozny Miotacz: -4% K)."
                                else: uwagi += f" 🌦️ Wiatr {w_msg_short} (Agresywny Miotacz: +4% K)."
                            else:
                                if mlb_stat_key == 'homeRuns':
                                    hr_mod = 1.0 + (w_mod_raw - 1.0) * 2.0
                                    korekta *= hr_mod
                                    if w_mod_raw > 1.0: uwagi += f" 🌦️ Wiatr {w_msg_short} (Zysk na HR)."
                                    else: uwagi += f" 🌦️ Wiatr {w_msg_short} (Strata na HR)."
                                elif mlb_stat_key == 'hits':
                                    hit_mod = 1.0 + (w_mod_raw - 1.0) * 0.5
                                    korekta *= hit_mod
                                    if w_mod_raw > 1.0: uwagi += f" 🌦️ Wiatr {w_msg_short} (+4% Hits)."
                                    else: uwagi += f" 🌦️ Wiatr {w_msg_short} (-4% Hits)."
                                else:
                                    korekta *= w_mod_raw
                                    uwagi += f" 🌦️ {w_data['msg']}."
                        else:
                            if "Wiatr" in w_data['msg'] or "Dach" in w_data['msg']:
                                uwagi += f" 🌦️ {w_data['msg']}."
                        
                        if p_hand and bat_side:
                            if bat_side == 'S': 
                                korekta *= 1.04; uwagi += " ⚔️ Switch Hitter (+4%)."
                            elif bat_side != p_hand: 
                                korekta *= 1.08; uwagi += f" ⚔️ Platoon Adv ({bat_side} vs {p_hand}) (+8%)."
                            else: 
                                korekta *= 0.95; uwagi += f" ⚔️ Hard Split ({bat_side} vs {p_hand}) (-5%)."
                            
                        if b_order > 0:
                            if b_order <= 3: korekta *= 1.05
                            elif b_order >= 8: korekta *= 0.90
                    
                    projekcja_finalna = baza_proj * korekta
                    prob_over = poisson_prob_over(projekcja_finalna, linia)
                    
                    typ = "OVER" if mlb_stat_key == 'homeRuns' else ("OVER" if prob_over > 0.50 else "UNDER")
                    true_prob = prob_over if typ == "OVER" else (1.0 - prob_over)
                    kurs_final = kurs_over if typ == "OVER" else kurs_under
                    
                    is_hr = (mlb_stat_key == 'homeRuns')
                    min_prob = 0.15 if is_hr else 0.55
                    
                    if true_prob <= min_prob: continue
                    ev_val = (true_prob * kurs_final) - 1.0 
                    if is_hr and ev_val < 0.05: continue
                    
                    if typ == "OVER":
                        pokrycie_l5 = int((sum(1 for x in vals[-5:] if x > linia) / 5) * 100) if len(vals) >= 5 else 0
                        pokrycie_l10 = int((sum(1 for x in vals[-10:] if x > linia) / 10) * 100) if len(vals) >= 10 else 0
                        pokrycie_sezon = int((sum(1 for x in vals if x > linia) / len(vals)) * 100)
                    else:
                        pokrycie_l5 = int((sum(1 for x in vals[-5:] if x < linia) / 5) * 100) if len(vals) >= 5 else 0
                        pokrycie_l10 = int((sum(1 for x in vals[-10:] if x < linia) / 10) * 100) if len(vals) >= 10 else 0
                        pokrycie_sezon = int((sum(1 for x in vals if x < linia) / len(vals)) * 100)
                        m_color = "rank-green" if m_color == "rank-red" else ("rank-red" if m_color == "rank-green" else "rank-yellow")
                    
                    if is_hr:
                        is_value_bet = ev_val >= 0.15 
                        is_safe_bet = true_prob >= 0.25 and pokrycie_l10 >= 20 
                    else:
                        is_value_bet = ev_val >= 0.03 
                        is_safe_bet = true_prob >= 0.75 and pokrycie_l5 >= 80
                        
                    is_stable_bet = (m_color == "rank-green")
                    is_graal_bet = is_value_bet and is_safe_bet and is_stable_bet
                    
                    if ev_val > 0.02:
                        znacznik = "🏆 GRAAL" if is_graal_bet else ("🎯 PEWNIAK" if is_safe_bet else ("💰 VALUE" if is_value_bet else "✅ DODANO"))
                        print(f"      {znacznik:<11}: {p_name:<20} | {nazwa_rynku_pl:<14} | EV: +{round(ev_val*100,1)}% | Szansa: {round(true_prob*100,1)}%")
                    
                    wyniki_props.append({
                        "zawodnik": p_name, "mecz": m_str, "data": DATA_DZIS, "rynek": nazwa_rynku_pl,
                        "linia": linia, "projekcja": round(projekcja_finalna, 2), "true_prob": true_prob,
                        "ev": round(ev_val, 3), "typ": typ, "kurs": kurs_final,
                        "l5": f"{pokrycie_l5}%", "l10": f"{pokrycie_l10}%",
                        "sezon": f"{pokrycie_sezon}%", "history": vals[-10:],
                        "uwagi": uwagi, "lokacja": "DOM" if is_today_home else "WYJ", "matchup_rank": m_rank,
                        "matchup_color": m_color, "opp_name": opp_name,
                        "is_value": is_value_bet, "is_safe": is_safe_bet, "is_stable": is_stable_bet, "is_graal": is_graal_bet
                    })

    wyniki_games = sorted(wyniki_games, key=lambda x: x['ev'], reverse=True)
    with open('mlb_games.json', 'w', encoding='utf-8') as f: json.dump(wyniki_games, f, ensure_ascii=False, indent=4)
    wyslij_plik_na_githuba('mlb_games.json', "Update MLB Game Lines & F5")
    print(f"\n✅ Zapisano {len(wyniki_games)} zyskownych typów na Linie Meczowe i F5.")

    wyniki_props = sorted(wyniki_props, key=lambda x: x['ev'], reverse=True)
    with open(MLB_JSON_FILE, 'w', encoding='utf-8') as f: json.dump(wyniki_props, f, ensure_ascii=False, indent=4)
    wyslij_plik_na_githuba(MLB_JSON_FILE, "MLB Data: Update Props")
    print(f"✅ Zapisano {len(wyniki_props)} typów na zawodników.")

if __name__ == "__main__":
    uruchom_mlb_pro()
