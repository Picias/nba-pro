import requests
import json
import time
import math
import os
import base64
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
MARKETS_GAMES = 'h2h,totals,spreads,h2h_1st_half,totals_1st_half'

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

PARK_FACTORS = {
    'Colorado Rockies': 1.15, 'Cincinnati Reds': 1.12, 'Boston Red Sox': 1.08,
    'Atlanta Athletics': 1.05, 'Texas Rangers': 1.04, 'Chicago White Sox': 1.03,
    'Seattle Mariners': 0.90, 'San Diego Padres': 0.93, 'Oakland Athletics': 0.94,
    'Cleveland Guardians': 0.95, 'Tampa Bay Rays': 0.96, 'New York Mets': 0.96
}

# ==========================================
# NARZĘDZIA POMOCNICZE
# ==========================================
def clean_team_name(name):
    if not name: return ""
    return name.lower().replace(".", "").replace(" ", "").replace("'", "").replace("-", "")

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

def wyslij_powiadomienie_telegram(wiadomosc):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": wiadomosc, "parse_mode": "HTML"}
    try: requests.post(url, json=payload, timeout=10)
    except: pass

def poisson_prob_over(lam, line):
    if lam <= 0: return 0.0
    k_max = math.floor(line) 
    prob_under = 0.0
    for k in range(k_max + 1):
        prob_under += (math.pow(lam, k) * math.exp(-lam)) / math.factorial(k)
    return 1.0 - prob_under 

# ==========================================
# 🌤️ MODUŁ POGODY & SPLITÓW
# ==========================================
def pobierz_pogode_covers():
    print("🌤️ Pobieram dane pogodowe z Covers.com (Wiatr i Stadiony)...")
    weather_data = {}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get("https://www.covers.com/sport/mlb/weather", headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        game_boxes = soup.find_all('div', class_='weather-event-box') 
        if not game_boxes: game_boxes = soup.find_all('div', class_='covers-weather-details')
            
        for box in game_boxes:
            text = box.text.lower()
            w_mod = 1.0; msg = "Dach/Brak wiatru"
            if "blowing out" in text or "out to" in text:
                w_mod = 1.08; msg = "💨 Wiatr wywiewa (+8% Runs)"
            elif "blowing in" in text or "in from" in text:
                w_mod = 0.92; msg = "🛑 Wiatr w twarz (-8% Runs)"
            elif "dome" in text or "roof closed" in text:
                w_mod = 1.0; msg = "🏟️ Zamknięty dach"
                
            for full_name in PARK_FACTORS.keys():
                if full_name.lower() in text or full_name.split()[-1].lower() in text:
                    weather_data[full_name] = {'mod': w_mod, 'msg': msg}
    except Exception as e:
        print(f"⚠️ Błąd pobierania pogody: {e}")
    
    global CACHE_WEATHER
    CACHE_WEATHER = weather_data
    return weather_data

def pobierz_ops_splits(team_id):
    if team_id in CACHE_TEAM_SPLITS: return CACHE_TEAM_SPLITS[team_id]
    
    ops_vs_lhp = LEAGUE_AVG_OPS
    ops_vs_rhp = LEAGUE_AVG_OPS
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

# ==========================================
# 📊 MODUŁ STATYSTYK DRUŻYNOWYCH MLB
# ==========================================
def generuj_pelny_raport_druzynowy_mlb():
    plik_raportu = 'mlb_teams.json'
    
    if os.path.exists(plik_raportu):
        mod_time = datetime.fromtimestamp(os.path.getmtime(plik_raportu))
        if mod_time.strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d'):
            return 

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
        
# ==========================================
# 📊 AUDYTOR MLB (AUTO-ROZLICZANIE)
# ==========================================
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
    
    if data_typow > DATA_DZIS: 
        return
        
    print(f"\n🕵️ Uruchamiam Głównego Audytora MLB: Rozliczam typy z daty {data_typow}...")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_typow}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    rzeczywiste_staty = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if 'dates' not in res or not res['dates']: 
            print("❌ MLB API: Brak rozegranych meczów w tym dniu.")
            return
            
        mecze = res['dates'][0]['games']
        print(f"🔍 Audytor: Znalazłem {len(mecze)} meczów w terminarzu. Skanuję twarde Boxscore'y...")
        
        ukonczone_mecze = 0
        for m in mecze:
            away_t = m['teams']['away']['team']['name']
            home_t = m['teams']['home']['team']['name']
            status_code = m['status']['statusCode']
            game_id = m['gamePk']
            
            if status_code in ['F', 'O', 'C'] or m['status']['abstractGameState'] == 'Final': 
                ukonczone_mecze += 1
                try:
                    # 1. Pobieranie boxscore dla Player Props
                    box_url = f"https://statsapi.mlb.com/api/v1/game/{game_id}/boxscore"
                    box_res = requests.get(box_url, headers=headers, timeout=5).json()
                    teams = box_res.get('teams', {})
                    
                    for team_side in ['away', 'home']:
                        players = teams.get(team_side, {}).get('players', {})
                        for p_key, p_data in players.items():
                            name = p_data.get('person', {}).get('fullName', '').lower().replace(".", "").replace("'", "").strip()
                            if not name: continue
                            b_stats = p_data.get('stats', {}).get('batting', {})
                            p_stats = p_data.get('stats', {}).get('pitching', {})
                            rzeczywiste_staty[name] = {
                                "K's": p_stats.get('strikeOuts', 0), 'Hits': b_stats.get('hits', 0), 
                                'Home Runs': b_stats.get('homeRuns', 0), 'Total Bases': b_stats.get('totalBases', 0), 
                                'Runs': b_stats.get('runs', 0), 'RBIs': b_stats.get('rbi', 0)
                            }
                            
                    # 2. Pobieranie danych dla Game Lines i F5
                    linescore = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game_id}/linescore", headers=headers).json()
                    innings = linescore.get('innings', [])
                    away_f5 = sum(i.get('away', {}).get('runs', 0) for i in innings[:5])
                    home_f5 = sum(i.get('home', {}).get('runs', 0) for i in innings[:5])
                    
                    away_fg = m['teams']['away'].get('score', 0)
                    home_fg = m['teams']['home'].get('score', 0)
                    
                    m_key = f"{away_t} @ {home_t}".lower()
                    rzeczywiste_staty[m_key] = {
                        'Mecz: Suma Runs': away_fg + home_fg,
                        'Mecz: Zwycięzca (ML)': home_t if home_fg > away_fg else away_t,
                        'F5 Inningów: Suma Runs': away_f5 + home_f5,
                        'F5 Inningów: ML': home_t if home_f5 > away_f5 else (away_t if away_f5 > home_f5 else "REMIS")
                    }
                except Exception as box_err: pass
                
        if ukonczone_mecze == 0:
            print("⚠️ Żaden mecz z tego dnia nie jest jeszcze w pełni zakończony.")
            return
    except Exception as e: return
            
    wygrane = przegrane = zwroty = profit = 0
    historia = []
    
    print("\n📝 ROZLICZANIE ZAKŁADÓW:")
    for typ in stare_typy:
        rynek = typ['rynek']
        linia = typ.get('linia', 0)
        zaw = typ.get('zawodnik', typ.get('zaklad', '')).lower().replace(".", "").replace("'", "").strip()
        mecz_key = typ.get('mecz', '').lower()
        
        is_game_line = "Mecz:" in rynek or "F5" in rynek
        search_key = mecz_key if is_game_line else zaw
        
        znaleziony_zaw = next((k for k in rzeczywiste_staty.keys() if search_key in k or k in search_key), None)
        if not znaleziony_zaw:
            historia.append({"zawodnik": typ.get('zawodnik', typ.get('zaklad', 'Mecz')), "rynek": rynek, "status": "ZWROT", "kategoria": "Zwykły Typ"})
            zwroty += 1; continue
            
        wynik = rzeczywiste_staty[znaleziony_zaw].get(rynek, 0)
        zaklad = str(typ.get('zaklad', typ.get('typ', '')))
        
        if "Zwycięzca" in rynek or "ML" in rynek:
            if wynik == "REMIS": czy_weszlo = None
            else: czy_weszlo = (zaklad.lower() == wynik.lower())
        else:
            if wynik == linia: czy_weszlo = None
            else: czy_weszlo = (zaklad == "OVER" and wynik > float(linia)) or (zaklad == "UNDER" and wynik < float(linia))
        
        if czy_weszlo is None:
            zwroty += 1; status = "➖ ZWROT"
        elif czy_weszlo: 
            wygrane += 1; profit += (typ.get('kurs', 1.0) - 1.0); status = "✅ WYGRANA"
        else: 
            przegrane += 1; profit -= 1.0; status = "❌ PRZEGRANA"
            
        is_value = typ.get('is_value', False); is_safe = typ.get('is_safe', False)
        is_stable = typ.get('is_stable', False); is_graal = typ.get('is_graal', False)
            
        etykiety = []
        if is_game_line: etykiety.append("📊 Typ Meczowy")
        else:
            if is_graal: etykiety.append("🏆 Graal")
            else:
                if is_value: etykiety.append("💰 Value")
                if is_safe: etykiety.append("🎯 Pewniak")
                if is_stable: etykiety.append("🛡️ Stabilny")
            
        historia.append({
            "zawodnik": typ.get('zawodnik', typ.get('zaklad', 'Mecz')), "rynek": rynek, 
            "typ": zaklad, "linia": linia, "kurs": typ.get('kurs', 0.0), "wynik_realny": wynik, "status": status, "kategoria": " | ".join(etykiety) if etykiety else "Zwykły Typ"
        })
            
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

# ==========================================
# 1. POBIERANIE DANYCH MLB
# ==========================================
def pobierz_oficjalny_terminarz_mlb(data_str):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_str}&hydrate=probablePitcher,lineups"
    headers = {'User-Agent': 'Mozilla/5.0'}
    baza_mlb = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if 'dates' in res and len(res['dates']) > 0:
            for m in res['dates'][0]['games']:
                home_team = m['teams']['home']['team']['name']; away_team = m['teams']['away']['team']['name']
                home_team_id = m['teams']['home']['team']['id']; away_team_id = m['teams']['away']['team']['id']
                home_p = m['teams']['home'].get('probablePitcher', {}); away_p = m['teams']['away'].get('probablePitcher', {})
                
                lineups_home = {p['id']: i+1 for i, p in enumerate(m['teams']['home'].get('lineups', {}).get('homePlayers', []))}
                lineups_away = {p['id']: i+1 for i, p in enumerate(m['teams']['away'].get('lineups', {}).get('awayPlayers', []))}
                
                klucz_meczu = f"{away_team} @ {home_team}".lower().replace("st. ", "st ")
                baza_mlb[klucz_meczu] = {
                    'home_team': home_team, 'home_team_id': home_team_id, 'away_team': away_team, 'away_team_id': away_team_id,
                    'home_pitcher': home_p.get('fullName', 'TBD'), 'home_pitcher_id': home_p.get('id', None), 'home_pitcher_hand': home_p.get('pitchHand', {}).get('code', 'R'),
                    'away_pitcher': away_p.get('fullName', 'TBD'), 'away_pitcher_id': away_p.get('id', None), 'away_pitcher_hand': away_p.get('pitchHand', {}).get('code', 'R'),
                    'lineups_home': lineups_home, 'lineups_away': lineups_away
                }
    except: pass
    return baza_mlb

def pobierz_statystyki_druzyn_mlb():
    global LEAGUE_AVG_K_RATE, LEAGUE_AVG_ERA
    print("📊 Pobieram statystyki zespołowe po ID (K-Rate i Team ERA)...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    url_hit = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=hitting&stats=season&gameType=R"
    try:
        res_h = requests.get(url_hit, headers=headers, timeout=10).json()
        stats_h = res_h.get('stats', [])
        if stats_h and stats_h[0].get('splits'):
            total_k, total_pa = 0, 0
            for team in stats_h[0]['splits']:
                k = team['stat'].get('strikeOuts', 0); pa = team['stat'].get('plateAppearances', 1)
                team_id = team['team']['id'] 
                CACHE_TEAM_K_RATE[team_id] = k / pa if pa > 0 else 0
                total_k += k; total_pa += pa
            if total_pa > 0: LEAGUE_AVG_K_RATE = total_k / total_pa
    except: pass

    url_pitch = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=pitching&stats=season&gameType=R"
    try:
        res_p = requests.get(url_pitch, headers=headers, timeout=10).json()
        stats_p = res_p.get('stats', [])
        if stats_p and stats_p[0].get('splits'):
            total_era = 0; count = 0
            for team in stats_p[0]['splits']:
                era_str = team['stat'].get('era', str(LEAGUE_AVG_ERA))
                era = float(era_str) if era_str != '-.--' else LEAGUE_AVG_ERA
                team_id = team['team']['id']
                CACHE_TEAM_ERA[team_id] = era
                total_era += era; count += 1
            if count > 0: LEAGUE_AVG_ERA = total_era / count
    except: pass

def pobierz_staty_miotacza_startowego(pitcher_id):
    if not pitcher_id: return {'era': LEAGUE_AVG_ERA, 'baa': LEAGUE_AVG_BAA}
    if pitcher_id in CACHE_PITCHER_STATS: return CACHE_PITCHER_STATS[pitcher_id]
    era, baa = LEAGUE_AVG_ERA, LEAGUE_AVG_BAA
    for s in [SEZON_MLB, SEZON_MLB - 1]:
        try:
            url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=season&group=pitching&season={s}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
            stats = res.get('stats', [])
            if stats and stats[0].get('splits'):
                stat_obj = stats[0]['splits'][0]['stat']
                era = float(stat_obj.get('era', str(LEAGUE_AVG_ERA))) if stat_obj.get('era', '-.--') != '-.--' else LEAGUE_AVG_ERA
                baa = float(stat_obj.get('avg', '.240')) if stat_obj.get('avg', '.---') != '.---' else LEAGUE_AVG_BAA
                break 
        except: pass
    CACHE_PITCHER_STATS[pitcher_id] = {'era': era, 'baa': baa}
    return CACHE_PITCHER_STATS[pitcher_id]

def oblicz_zmeczenie_bullpenu(team_id, data_dzis_str):
    if team_id in CACHE_BULLPEN_FATIGUE: return CACHE_BULLPEN_FATIGUE[team_id]
    dzis = datetime.strptime(data_dzis_str, '%Y-%m-%d')
    start_date = (dzis - timedelta(days=3)).strftime('%Y-%m-%d')
    end_date = (dzis - timedelta(days=1)).strftime('%Y-%m-%d')
    
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&startDate={start_date}&endDate={end_date}"
    rozegrane_mecze = 0
    try:
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
    headers = {'User-Agent': 'Mozilla/5.0'}
    historia_pelna = []
    
    for s in [SEZON_MLB, SEZON_MLB - 1]:
        try:
            url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={s}"
            res = requests.get(url, headers=headers, timeout=10).json()
            if 'stats' in res and len(res['stats']) > 0:
                splits = res['stats'][0].get('splits', [])
                for game in reversed(splits):
                    st = game.get('stat', {})
                    if typ_gracza == "pitcher" and float(st.get('inningsPitched', '0')) < 3.0: continue
                    if typ_gracza == "batter" and st.get('atBats', 0) < 2: continue
                    
                    historia_pelna.append({
                        'val': st.get(stat_key if typ_gracza == "batter" else 'strikeOuts', 0),
                        'isHome': game.get('isHome', False)
                    })
                    if len(historia_pelna) >= 15: break
        except: pass
        if len(historia_pelna) >= 15: break

    historia_pelna.reverse() 
    CACHE_PLAYER_LOGS[cache_key] = historia_pelna
    return historia_pelna

# ==========================================
# 3. GŁÓWNA PĘTLA BOTA (GAME LINES & PROPS)
# ==========================================
def uruchom_mlb_pro():
    print("==================================================")
    print("🚀 QUANT AI BOTS: MLB PRO ULTIMATE v7.0 (Full Engine)")
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
        print("📡 Pobieram listę zdarzeń (The Odds API)...")
        events = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={ODDS_API_KEY}").json()
        if isinstance(events, dict) and 'message' in events: 
            print(f"❌ ODRZUCONO ZAPYTANIE: {events['message']}")
            return []
    except Exception as e: 
        print(f"❌ BŁĄD POŁĄCZENIA Z API: {e}")
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
        w_data = CACHE_WEATHER.get(ev['home_team'], {'mod': 1.0, 'msg': 'Neutralnie/Dach'})
        p_factor = PARK_FACTORS.get(ev['home_team'], 1.0)
        
        # --- 🧮 KALKULATOR GAME LINES (Model Ważony + F5) ---
        away_ops_splits = pobierz_ops_splits(away_t_id)
        home_ops_splits = pobierz_ops_splits(home_t_id)
        home_p_hand = dane_oficjalne.get('home_pitcher_hand', 'R')
        away_p_hand = dane_oficjalne.get('away_pitcher_hand', 'R')
        home_p_stats = pobierz_staty_miotacza_startowego(dane_oficjalne.get('home_pitcher_id'))
        away_p_stats = pobierz_staty_miotacza_startowego(dane_oficjalne.get('away_pitcher_id'))
        home_bp = oblicz_zmeczenie_bullpenu(home_t_id, DATA_DZIS)
        away_bp = oblicz_zmeczenie_bullpenu(away_t_id, DATA_DZIS)

        # FULL GAME (65% SP / 35% BP)
        away_ops_vs_sp = away_ops_splits['vs_LHP'] if home_p_hand == 'L' else away_ops_splits['vs_RHP']
        away_ops_vs_bp = (away_ops_splits['vs_LHP'] + away_ops_splits['vs_RHP']) / 2.0
        away_true_ops_full = (away_ops_vs_sp * 0.65) + (away_ops_vs_bp * 0.35)
        away_base_runs_fg = (away_true_ops_full / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS
        away_proj_runs_fg = away_base_runs_fg * (home_p_stats['era'] / LEAGUE_AVG_ERA) * home_bp['korekta'] * p_factor * w_data['mod']
        
        home_ops_vs_sp = home_ops_splits['vs_LHP'] if away_p_hand == 'L' else home_ops_splits['vs_RHP']
        home_ops_vs_bp = (home_ops_splits['vs_LHP'] + home_ops_splits['vs_RHP']) / 2.0
        home_true_ops_full = (home_ops_vs_sp * 0.65) + (home_ops_vs_bp * 0.35)
        home_base_runs_fg = (home_true_ops_full / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS
        home_proj_runs_fg = home_base_runs_fg * (away_p_stats['era'] / LEAGUE_AVG_ERA) * away_bp['korekta'] * p_factor * w_data['mod'] * 1.04 
        
        total_proj_runs_fg = round(away_proj_runs_fg + home_proj_runs_fg, 2)
        try: home_win_prob_fg = (home_proj_runs_fg**1.83) / (home_proj_runs_fg**1.83 + away_proj_runs_fg**1.83)
        except: home_win_prob_fg = 0.5

        # F5 INNINGS (100% SP)
        away_base_runs_f5 = (away_ops_vs_sp / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS_F5
        away_proj_runs_f5 = away_base_runs_f5 * (home_p_stats['era'] / LEAGUE_AVG_ERA) * p_factor * w_data['mod']
        home_base_runs_f5 = (home_ops_vs_sp / LEAGUE_AVG_OPS) * LEAGUE_AVG_RUNS_F5
        home_proj_runs_f5 = home_base_runs_f5 * (away_p_stats['era'] / LEAGUE_AVG_ERA) * p_factor * w_data['mod'] * 1.04
        
        total_proj_runs_f5 = round(away_proj_runs_f5 + home_proj_runs_f5, 2)
        try: home_win_prob_f5 = (home_proj_runs_f5**1.83) / (home_proj_runs_f5**1.83 + away_proj_runs_f5**1.83)
        except: home_win_prob_f5 = 0.5

        print(f"  📈 Kalkulator Mecz: {ev['away_team']} {round(away_proj_runs_fg, 1)} - {round(home_proj_runs_fg, 1)} {ev['home_team']} (Suma: {total_proj_runs_fg})")
        print(f"  ⏱️ Kalkulator F5: Suma {total_proj_runs_f5} runs po 5 inningach.")

        g_insights = f"🌦️ {w_data['msg']} | 🏟️ Park: {p_factor}x<br>"
        g_insights += f"⚾ <b>{ev['home_team']}</b> vs {away_p_hand}HP: OPS {round(home_ops_vs_sp,3)} | SP ERA: {round(home_p_stats['era'],2)} | {home_bp['uwaga']}<br>"
        g_insights += f"⚾ <b>{ev['away_team']}</b> vs {home_p_hand}HP: OPS {round(away_ops_vs_sp,3)} | SP ERA: {round(away_p_stats['era'],2)} | {away_bp['uwaga']}"

        # --- 📈 POBIERANIE KURSÓW (PROPS + GAMES) DLA KONKRETNEGO MECZU ---
        try:
            time.sleep(0.1) # Lekki bufor na limity API
            res_odds = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS_PROPS},{MARKETS_GAMES}&oddsFormat=decimal").json()
        except Exception as e: 
            print(f"  ❌ Błąd pobierania kursów dla tego meczu: {e}")
            continue
        
        # Ekstrakcja Kursów
        game_lines = {'h2h': {}, 'totals': {}, 'h2h_f5': {}, 'totals_f5': {}}
        for bm in res_odds.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                if mkt['key'] == 'h2h':
                    for oc in mkt['outcomes']: game_lines['h2h'][oc['name']] = oc['price']
                elif mkt['key'] == 'totals':
                    for oc in mkt['outcomes']: 
                        game_lines['totals']['point'] = oc['point']
                        game_lines['totals'][oc['name']] = oc['price']
                elif mkt['key'] == 'h2h_1st_half':
                    for oc in mkt['outcomes']: game_lines['h2h_f5'][oc['name']] = oc['price']
                elif mkt['key'] == 'totals_1st_half':
                    for oc in mkt['outcomes']: 
                        game_lines['totals_f5']['point'] = oc['point']
                        game_lines['totals_f5'][oc['name']] = oc['price']

        # --- 🎯 EWALUACJA ZAKŁADÓW MECZOWYCH (Z wizualizacją w konsoli) ---
        if game_lines['totals'] and 'Over' in game_lines['totals']:
            t_line = game_lines['totals']['point']
            t_over = game_lines['totals']['Over']
            t_under = game_lines['totals']['Under']
            over_prob = 1.0 - poisson_prob_over(total_proj_runs_fg, t_line)
            ev_o = (over_prob * t_over) - 1; ev_u = ((1-over_prob) * t_under) - 1
            
            print(f"    🎲 Linia Totals {t_line} | Szansa OVER: {round(over_prob*100,1)}% (EV: {round(ev_o*100,1)}%) | Szansa UNDER: {round((1-over_prob)*100,1)}% (EV: {round(ev_u*100,1)}%)")
            if ev_o > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Suma Runs", "zaklad": "OVER", "linia": t_line, "kurs": t_over, "projekcja": total_proj_runs_fg, "szansa": round(over_prob * 100, 1), "ev": round(ev_o, 3), "uwagi": g_insights})
            elif ev_u > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Suma Runs", "zaklad": "UNDER", "linia": t_line, "kurs": t_under, "projekcja": total_proj_runs_fg, "szansa": round((1-over_prob) * 100, 1), "ev": round(ev_u, 3), "uwagi": g_insights})

        if game_lines['h2h'] and ev['home_team'] in game_lines['h2h']:
            h_kurs = game_lines['h2h'][ev['home_team']]
            a_kurs = game_lines['h2h'][ev['away_team']]
            ev_h = (home_win_prob_fg * h_kurs) - 1; ev_a = ((1-home_win_prob_fg) * a_kurs) - 1
            
            print(f"    ⚔️ ML Home: {round(home_win_prob_fg*100,1)}% (EV: {round(ev_h*100,1)}%) | ML Away: {round((1-home_win_prob_fg)*100,1)}% (EV: {round(ev_a*100,1)}%)")
            if ev_h > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Zwycięzca (ML)", "zaklad": ev['home_team'], "linia": "-", "kurs": h_kurs, "projekcja": f"{round(home_proj_runs_fg,1)} - {round(away_proj_runs_fg,1)}", "szansa": round(home_win_prob_fg * 100, 1), "ev": round(ev_h, 3), "uwagi": g_insights})
            elif ev_a > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "Mecz: Zwycięzca (ML)", "zaklad": ev['away_team'], "linia": "-", "kurs": a_kurs, "projekcja": f"{round(away_proj_runs_fg,1)} - {round(home_proj_runs_fg,1)}", "szansa": round((1-home_win_prob_fg) * 100, 1), "ev": round(ev_a, 3), "uwagi": g_insights})

        if game_lines['totals_f5'] and 'Over' in game_lines['totals_f5']:
            t_line_f5 = game_lines['totals_f5']['point']
            t_over_f5 = game_lines['totals_f5']['Over']
            t_under_f5 = game_lines['totals_f5']['Under']
            over_prob_f5 = 1.0 - poisson_prob_over(total_proj_runs_f5, t_line_f5)
            ev_o_f5 = (over_prob_f5 * t_over_f5) - 1; ev_u_f5 = ((1-over_prob_f5) * t_under_f5) - 1
            
            print(f"    🎲 F5 Totals {t_line_f5} | Szansa OVER: {round(over_prob_f5*100,1)}% (EV: {round(ev_o_f5*100,1)}%) | Szansa UNDER: {round((1-over_prob_f5)*100,1)}% (EV: {round(ev_u_f5*100,1)}%)")
            if ev_o_f5 > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "F5 Inningów: Suma Runs", "zaklad": "OVER", "linia": t_line_f5, "kurs": t_over_f5, "projekcja": total_proj_runs_f5, "szansa": round(over_prob_f5 * 100, 1), "ev": round(ev_o_f5, 3), "uwagi": g_insights})
            elif ev_u_f5 > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "F5 Inningów: Suma Runs", "zaklad": "UNDER", "linia": t_line_f5, "kurs": t_under_f5, "projekcja": total_proj_runs_f5, "szansa": round((1-over_prob_f5) * 100, 1), "ev": round(ev_u_f5, 3), "uwagi": g_insights})

        if game_lines['h2h_f5'] and ev['home_team'] in game_lines['h2h_f5']:
            h_kurs_f5 = game_lines['h2h_f5'][ev['home_team']]
            a_kurs_f5 = game_lines['h2h_f5'][ev['away_team']]
            ev_h_f5 = (home_win_prob_f5 * h_kurs_f5) - 1; ev_a_f5 = ((1-home_win_prob_f5) * a_kurs_f5) - 1
            
            print(f"    ⚔️ F5 ML Home: {round(home_win_prob_f5*100,1)}% (EV: {round(ev_h_f5*100,1)}%) | F5 ML Away: {round((1-home_win_prob_f5)*100,1)}% (EV: {round(ev_a_f5*100,1)}%)")
            if ev_h_f5 > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "F5 Inningów: ML", "zaklad": ev['home_team'], "linia": "-", "kurs": h_kurs_f5, "projekcja": f"{round(home_proj_runs_f5,1)} - {round(away_proj_runs_f5,1)}", "szansa": round(home_win_prob_f5 * 100, 1), "ev": round(ev_h_f5, 3), "uwagi": g_insights})
            elif ev_a_f5 > 0.05: wyniki_games.append({"mecz": m_str, "data": DATA_DZIS, "rynek": "F5 Inningów: ML", "zaklad": ev['away_team'], "linia": "-", "kurs": a_kurs_f5, "projekcja": f"{round(away_proj_runs_f5,1)} - {round(home_proj_runs_f5,1)}", "szansa": round((1-home_win_prob_f5) * 100, 1), "ev": round(ev_a_f5, 3), "uwagi": g_insights})

        # --- 🏏 ANALIZA ZAWODNIKÓW (PROPS) ---
        h_roster = {}
        a_roster = {}
        try:
            res_h = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['home_team_id']}/roster?hydrate=person", timeout=10).json()
            h_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_h.get('roster', [])}
            
            res_a = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['away_team_id']}/roster?hydrate=person", timeout=10).json()
            a_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_a.get('roster', [])}
        except: pass

        for bm in res_odds.get('bookmakers', []):
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
                    h_clean = dane_oficjalne['home_pitcher'].lower().replace(".", "").strip()
                    a_clean = dane_oficjalne['away_pitcher'].lower().replace(".", "").strip()
                    p_clean = p_name.lower().replace(".", "").strip()
                    
                    if rola == 'pitcher':
                        if p_clean in h_clean or h_clean in p_clean: 
                            player_id = dane_oficjalne['home_pitcher_id']
                            is_today_home = True
                            opp_team_id = dane_oficjalne['away_team_id']
                            opp_name = ev['away_team']
                        elif p_clean in a_clean or a_clean in p_clean: 
                            player_id = dane_oficjalne['away_pitcher_id']
                            is_today_home = False
                            opp_team_id = dane_oficjalne['home_team_id']
                            opp_name = ev['home_team']
                    else:
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
                    
                    if rola == 'pitcher':
                        opp_k_rate = CACHE_TEAM_K_RATE.get(opp_team_id, LEAGUE_AVG_K_RATE)
                        korekta *= max(0.85, min(1.15, opp_k_rate / LEAGUE_AVG_K_RATE))
                        m_color = "rank-green" if korekta > 1.05 else "rank-red"
                        m_rank = f"K-Rate rywala: {round(opp_k_rate*100,1)}%"
                    else:
                        opp_pitcher_id = dane_oficjalne['away_pitcher_id'] if is_today_home else dane_oficjalne['home_pitcher_id']
                        opp_pitcher_name = dane_oficjalne['away_pitcher'] if is_today_home else dane_oficjalne['home_pitcher']
                        
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
                        
                        pf = PARK_FACTORS.get(ev['home_team'], 1.0)
                        if mlb_stat_key == 'homeRuns': pf = ((pf - 1.0) * 1.5) + 1.0 
                        if pf != 1.0: 
                            korekta *= pf
                            uwagi += f" 🏟️ Stadion PF: {round(pf, 2)}x."
                        
                        if w_data['mod'] != 1.0:
                            korekta *= w_data['mod']
                            uwagi += f" 🌦️ Pogoda: {w_data['msg']}."
                        
                        p_hand = dane_oficjalne['away_pitcher_hand'] if is_today_home else dane_oficjalne['home_pitcher_hand']
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
                    
                    if true_prob <= min_prob: 
                        continue
                    
                    ev_val = (true_prob * kurs_final) - 1.0 
                    
                    if is_hr and ev_val < 0.05:
                        continue
                    
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
                        is_value_bet = ev_val >= 0.04
                        is_safe_bet = true_prob >= 0.75 and pokrycie_l5 >= 80
                        
                    is_stable_bet = (m_color == "rank-green")
                    is_graal_bet = is_value_bet and is_safe_bet and is_stable_bet
                    
                    znacznik = "🏆 GRAAL" if is_graal_bet else ("🎯 PEWNIAK" if is_safe_bet else ("💰 VALUE" if is_value_bet else "✅ DODANO"))
                    print(f"    {znacznik:<11}: {p_name:<20} | {nazwa_rynku_pl:<14} | EV: +{round(ev_val*100,1)}% | Szansa: {round(true_prob*100,1)}%")
                    
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

    # Sortowanie i Zapis
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
