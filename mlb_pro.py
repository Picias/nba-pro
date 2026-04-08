import requests
import json
import time
import math
import os
import base64
from datetime import datetime, timedelta

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
MARKETS = 'pitcher_strikeouts,batter_hits,batter_home_runs,batter_total_bases,batter_runs_scored,batter_rbis' 
SEZON_MLB = 2026

DATA_DZIS = datetime.now().strftime('%Y-%m-%d')
MLB_JSON_FILE = 'mlb.json'
STATS_MLB_FILE = 'statystyki_mlb.json'

CACHE_PLAYER_LOGS = {}
CACHE_TEAM_K_RATE = {} # Kluczem jest teraz ID drużyny, nie jej nazwa!
CACHE_TEAM_ERA = {}    # Kluczem jest teraz ID drużyny, nie jej nazwa!
CACHE_ROSTERS = {}
CACHE_PITCHER_STATS = {}

LEAGUE_AVG_K_RATE = 0.225 
LEAGUE_AVG_ERA = 4.20
LEAGUE_AVG_BAA = 0.240 

PARK_FACTORS = {
    'Colorado Rockies': 1.15, 'Cincinnati Reds': 1.12, 'Boston Red Sox': 1.08,
    'Atlanta Athletics': 1.05, 'Texas Rangers': 1.04, 'Chicago White Sox': 1.03,
    'Seattle Mariners': 0.90, 'San Diego Padres': 0.93, 'Oakland Athletics': 0.94,
    'Cleveland Guardians': 0.95, 'Tampa Bay Rays': 0.96, 'New York Mets': 0.96
}

# ==========================================
# NARZĘDZIA POMOCNICZE
# ==========================================
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
# 📊 AUDYTOR MLB (AUTO-ROZLICZANIE)
# ==========================================
def rozlicz_wczorajsze_typy_mlb():
    try:
        with open(MLB_JSON_FILE, 'r', encoding='utf-8') as f: stare_typy = json.load(f)
    except: return

    if not stare_typy: return
    data_typow = stare_typy[0].get('data', '2000-01-01')
    if data_typow >= DATA_DZIS: return
        
    print(f"🕵️ Uruchamiam Audytora MLB: Rozliczam typy z ({data_typow})...")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_typow}&hydrate=boxscore"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    rzeczywiste_staty = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if 'dates' not in res or not res['dates']: return
        mecze = res['dates'][0]['games']
        for m in mecze:
            if m['status']['statusCode'] in ['F', 'O']: 
                box = m.get('boxscore', {}).get('teams', {})
                for team_side in ['away', 'home']:
                    players = box.get(team_side, {}).get('players', {})
                    for p_key, p_data in players.items():
                        name = p_data['person']['fullName'].lower().replace(".", "").replace("'", "").strip()
                        b_stats = p_data.get('stats', {}).get('batting', {})
                        p_stats = p_data.get('stats', {}).get('pitching', {})
                        if b_stats or p_stats:
                            rzeczywiste_staty[name] = {
                                "K's": p_stats.get('strikeOuts', 0),
                                'Hits': b_stats.get('hits', 0), 'Home Runs': b_stats.get('homeRuns', 0),
                                'Total Bases': b_stats.get('totalBases', 0), 'Runs': b_stats.get('runs', 0),
                                'RBIs': b_stats.get('rbi', 0)
                            }
    except Exception as e:
        print(f"❌ Błąd Audytora MLB: {e}")
        return
            
    wygrane = przegrane = zwroty = profit = 0
    historia = []
    kategorie = {"graal": {"w":0,"t":0}, "value": {"w":0,"t":0}, "safe": {"w":0,"t":0}, "stable": {"w":0,"t":0}}
    
    for typ in stare_typy:
        ma_kategorie = typ.get('is_graal', False) or typ.get('is_value', False) or typ.get('is_safe', False) or typ.get('is_stable', False)
        
        is_hr_bet = (typ.get('rynek') == 'Home Runs')
        if not ma_kategorie:
            if typ.get('ev', 0) < 0.05 or typ.get('true_prob', 0) < (0.15 if is_hr_bet else 0.55): 
                continue
            
        zaw = typ['zawodnik'].lower().replace(".", "").replace("'", "").strip()
        rynek = typ['rynek']
        
        # 🧠 INTELIGENTNE SZUKANIE (Odporność na "Jr.", "Sr.", "II")
        znaleziony_zaw = next((k for k in rzeczywiste_staty.keys() if zaw in k or k in zaw), None)
        
        if not znaleziony_zaw:
            historia.append({"zaklad": typ['zawodnik'], "wynik": "DNP/Przełożony", "status": "ZWROT", "kategoria": typ.get("kategoria", "Zwykły Typ")})
            zwroty += 1; continue
            
        wynik = rzeczywiste_staty[znaleziony_zaw].get(rynek, 0)
        czy_weszlo = (typ['typ'] == "OVER" and wynik > typ['linia']) or (typ['typ'] == "UNDER" and wynik < typ['linia'])
        
        if czy_weszlo: wygrane += 1; profit += (typ['kurs'] - 1.0); status = "✅ WYGRANA"
        else: przegrane += 1; profit -= 1.0; status = "❌ PRZEGRANA"
            
        is_value = typ.get('is_value', False); is_safe = typ.get('is_safe', False)
        is_stable = typ.get('is_stable', False); is_graal = typ.get('is_graal', False)
        
        if is_value: kategorie["value"]["t"] += 1; kategorie["value"]["w"] += (1 if czy_weszlo else 0)
        if is_safe: kategorie["safe"]["t"] += 1; kategorie["safe"]["w"] += (1 if czy_weszlo else 0)
        if is_stable: kategorie["stable"]["t"] += 1; kategorie["stable"]["w"] += (1 if czy_weszlo else 0)
        if is_graal: kategorie["graal"]["t"] += 1; kategorie["graal"]["w"] += (1 if czy_weszlo else 0)
            
        etykiety = []
        if is_graal: etykiety.append("🏆 Graal")
        else:
            if is_value: etykiety.append("💰 Value")
            if is_safe: etykiety.append("🎯 Pewniak")
            if is_stable: etykiety.append("🛡️ Stabilny")
            
        historia.append({"zawodnik": typ['zawodnik'], "rynek": rynek, "linia": typ['linia'], "wynik_realny": wynik, "status": status, "kategoria": " | ".join(etykiety) if etykiety else "Zwykły Typ"})
            
    suma = wygrane + przegrane
    if suma > 0:
        hit_rate = round((wygrane / suma) * 100, 1); roi = round((profit / suma) * 100, 1)
        try:
            with open(STATS_MLB_FILE, 'r', encoding='utf-8') as f: baza_stat = json.load(f)
        except: baza_stat = []
        baza_stat = [r for r in baza_stat if r['data_meczow'] != data_typow]
        baza_stat.insert(0, {"data_meczow": data_typow, "wygrane": wygrane, "przegrane": przegrane, "zwroty": zwroty, "hit_rate": f"{hit_rate}%", "profit_jednostki": round(profit, 2), "roi": f"{roi}%", "kategorie": kategorie, "detale": historia})
        with open(STATS_MLB_FILE, 'w', encoding='utf-8') as f: json.dump(baza_stat, f, ensure_ascii=False, indent=4)
        print(f"✅ Raport MLB gotowy! Hit Rate: {hit_rate}%, ROI: {roi}%")
        wyslij_plik_na_githuba(STATS_MLB_FILE, f"Auto-Raport MLB ({data_typow})")
        
# ==========================================
# 1. POBIERANIE DANYCH MLB
# ==========================================
def pobierz_oficjalny_terminarz_mlb(data_str):
    print(f"⚾ Pobieram kalendarz i składy na {data_str}...")
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
    
    # Ważne: sportId=1 zapewnia, że pobieramy statystyki głównych drużyn MLB, a nie rezerw czy uniwersytetów
    url_hit = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=hitting&stats=season&gameType=R"
    try:
        res_h = requests.get(url_hit, headers=headers, timeout=10).json()
        stats_h = res_h.get('stats', [])
        if not stats_h or not stats_h[0].get('splits'):
            res_h = requests.get(url_hit.replace(str(SEZON_MLB), str(SEZON_MLB - 1)), headers=headers, timeout=10).json()
            stats_h = res_h.get('stats', [])
            
        if stats_h and stats_h[0].get('splits'):
            total_k, total_pa = 0, 0
            for team in stats_h[0]['splits']:
                k = team['stat'].get('strikeOuts', 0); pa = team['stat'].get('plateAppearances', 1)
                team_id = team['team']['id'] # KLUCZEM JEST TERAZ NUMER ID
                CACHE_TEAM_K_RATE[team_id] = k / pa if pa > 0 else 0
                total_k += k; total_pa += pa
            if total_pa > 0: LEAGUE_AVG_K_RATE = total_k / total_pa
    except: pass

    url_pitch = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB}&sportId=1&group=pitching&stats=season&gameType=R"
    try:
        res_p = requests.get(url_pitch, headers=headers, timeout=10).json()
        stats_p = res_p.get('stats', [])
        if not stats_p or not stats_p[0].get('splits'):
            res_p = requests.get(url_pitch.replace(str(SEZON_MLB), str(SEZON_MLB - 1)), headers=headers, timeout=10).json()
            stats_p = res_p.get('stats', [])
            
        if stats_p and stats_p[0].get('splits'):
            total_era = 0; count = 0
            for team in stats_p[0]['splits']:
                era_str = team['stat'].get('era', str(LEAGUE_AVG_ERA))
                if era_str == '-.--': era_str = str(LEAGUE_AVG_ERA) # Ochrona przed ValueError "nieskończoności"
                era = float(era_str)
                
                team_id = team['team']['id'] # KLUCZEM JEST TERAZ NUMER ID
                CACHE_TEAM_ERA[team_id] = era
                total_era += era; count += 1
            if count > 0: LEAGUE_AVG_ERA = total_era / count
            print(f"✅ Zoptymalizowane średnie ligowe: K-Rate={round(LEAGUE_AVG_K_RATE*100,1)}% | ERA={round(LEAGUE_AVG_ERA,2)}")
    except: pass

def pobierz_staty_miotacza_startowego(pitcher_id):
    if not pitcher_id: return {'era': LEAGUE_AVG_ERA, 'baa': LEAGUE_AVG_BAA}
    if pitcher_id in CACHE_PITCHER_STATS: return CACHE_PITCHER_STATS[pitcher_id]
    
    era = LEAGUE_AVG_ERA
    baa = LEAGUE_AVG_BAA
    for s in [SEZON_MLB, SEZON_MLB - 1]:
        try:
            url = f"https://statsapi.mlb.com/api/v1/people/{pitcher_id}/stats?stats=season&group=pitching&season={s}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
            stats = res.get('stats', [])
            if stats and stats[0].get('splits'):
                stat_obj = stats[0]['splits'][0]['stat']
                
                # Zabezpieczenia na start sezonu
                era_str = stat_obj.get('era', str(LEAGUE_AVG_ERA))
                if era_str == '-.--': era_str = str(LEAGUE_AVG_ERA)
                era = float(era_str)
                
                avg_str = stat_obj.get('avg', '.240')
                if avg_str == '.---': avg_str = '.240'
                baa = float(avg_str) if avg_str.startswith('.') else LEAGUE_AVG_BAA
                break 
        except: pass
    
    CACHE_PITCHER_STATS[pitcher_id] = {'era': era, 'baa': baa}
    return CACHE_PITCHER_STATS[pitcher_id]

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
# 2. GŁÓWNA PĘTLA
# ==========================================
def uruchom_mlb_pro():
    print("==================================================")
    print("🚀 QUANT AI BOTS: MLB PRO ULTIMATE v4.6 (Culoodporny)")
    print("==================================================")
    
    if not os.path.exists(STATS_MLB_FILE):
        with open(STATS_MLB_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
        wyslij_plik_na_githuba(STATS_MLB_FILE, "Inicjalizacja pustego pliku")
    
    rozlicz_wczorajsze_typy_mlb()
    pobierz_statystyki_druzyn_mlb()
    baza_mlb = pobierz_oficjalny_terminarz_mlb(DATA_DZIS)
    
    try:
        print("📡 Pobieram kursy (The Odds API)...")
        events = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={ODDS_API_KEY}").json()
        if isinstance(events, dict) and 'message' in events: 
            print(f"❌ ODRZUCONO ZAPYTANIE: {events['message']}")
            return []
    except Exception as e: 
        print(f"❌ BŁĄD POŁĄCZENIA Z API: {e}")
        return []

    if not isinstance(events, list): return []
    mecze_dzis = [e for e in events if (datetime.strptime(e['commence_time'], '%Y-%m-%dT%H:%M:%SZ') - timedelta(hours=5)).strftime('%Y-%m-%d') == DATA_DZIS]
    wyniki = []
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
        print(f"🗂️ Pobieranie składów i precyzyjne dopasowywanie statystyk...")
        
        h_roster = {}
        a_roster = {}
        try:
            res_h = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['home_team_id']}/roster?hydrate=person", timeout=10).json()
            h_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_h.get('roster', [])}
            
            res_a = requests.get(f"https://statsapi.mlb.com/api/v1/teams/{dane_oficjalne['away_team_id']}/roster?hydrate=person", timeout=10).json()
            a_roster = {p['person']['fullName'].lower().replace(".", "").strip(): p['person'] for p in res_a.get('roster', [])}
        except: pass
        
        try:
            res_odds = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal").json()
        except: continue
        
        for bm in res_odds.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                if mkt['key'] not in rynek_map: continue
                nazwa_rynku_pl, rola, mlb_stat_key = rynek_map[mkt['key']]
                
                for oc in mkt['outcomes']:
                    if oc['name'] != 'Over': continue
                    p_name = oc['description']; linia = oc['point']; kurs = oc['price']
                    
                    if mlb_stat_key == 'totalBases': linia = 1.5
                    elif mlb_stat_key == 'hits': linia = 0.5
                    
                    if f"{p_name}_{mkt['key']}" in przetworzeni_zawodnicy: continue
                    przetworzeni_zawodnicy.add(f"{p_name}_{mkt['key']}")
                    
                    player_id = None; is_today_home = False; opp_team_id = None; opp_name = ""; bat_side = 'R'; b_order = 0
                    h_clean = dane_oficjalne['home_pitcher'].lower().replace(".", "").strip()
                    a_clean = dane_oficjalne['away_pitcher'].lower().replace(".", "").strip()
                    p_clean = p_name.lower().replace(".", "").strip()
                    
                    # Logika przypisywania z twardym ID przeciwnika
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
                        # Sztywny odczyt K-Rate po Team ID
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
                        
                        # Sztywny odczyt ERA po Team ID
                        opp_era = CACHE_TEAM_ERA.get(opp_team_id, LEAGUE_AVG_ERA)
                        era_korekta = max(0.90, min(1.10, opp_era / LEAGUE_AVG_ERA))
                        
                        korekta *= (baa_korekta * era_korekta)
                        
                        uwagi += f" ⚾ SP: {opp_pitcher_name} (ERA: {round(p_stats['era'], 2)}, BAA: {str(p_stats['baa']).lstrip('0')})."
                        uwagi += f" 🛡️ Bullpen ERA: {round(opp_era, 2)}."
                        
                        pf = PARK_FACTORS.get(ev['home_team'], 1.0)
                        if mlb_stat_key == 'homeRuns': pf = ((pf - 1.0) * 1.5) + 1.0 
                        if pf != 1.0: 
                            korekta *= pf
                            uwagi += f" 🏟️ Stadion PF: {round(pf, 2)}x."
                        
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
                    
                    # LOGIKA DLA HOME RUNÓW
                    is_hr = (mlb_stat_key == 'homeRuns')
                    min_prob = 0.15 if is_hr else 0.55
                    
                    if true_prob <= min_prob: 
                        print(f"  ❌ Odrzucono (Szansa): {p_name:<20} | {nazwa_rynku_pl:<14} | Szansa: {round(true_prob*100,1)}%")
                        continue
                    
                    ev_val = (true_prob * (kurs if typ == "OVER" else 1.85)) - 1.0
                    
                    if is_hr and ev_val < 0.05:
                        print(f"  ❌ Odrzucono (Złe EV) : {p_name:<20} | {nazwa_rynku_pl:<14} | EV: {round(ev_val*100,1)}%")
                        continue
                    
                    pokrycie_l5 = int((sum(1 for x in vals[-5:] if x > linia) / 5) * 100) if len(vals) >= 5 else 0
                    pokrycie_l10 = int((sum(1 for x in vals[-10:] if x > linia) / 10) * 100) if len(vals) >= 10 else 0
                    
                    if is_hr:
                        is_value_bet = ev_val >= 0.15 
                        is_safe_bet = true_prob >= 0.25 and pokrycie_l10 >= 20 
                    else:
                        is_value_bet = ev_val >= 0.04
                        is_safe_bet = true_prob >= 0.75 and pokrycie_l5 >= 80
                        
                    is_stable_bet = (m_color == "rank-green")
                    is_graal_bet = is_value_bet and is_safe_bet and is_stable_bet
                    
                    znacznik = "🏆 GRAAL" if is_graal_bet else ("🎯 PEWNIAK" if is_safe_bet else ("💰 VALUE" if is_value_bet else "✅ DODANO"))
                    print(f"  {znacznik:<11}: {p_name:<20} | {nazwa_rynku_pl:<14} | EV: +{round(ev_val*100,1)}% | Szansa: {round(true_prob*100,1)}%")
                    
                    wyniki.append({
                        "zawodnik": p_name, "mecz": m_str, "data": DATA_DZIS, "rynek": nazwa_rynku_pl,
                        "linia": linia, "projekcja": round(projekcja_finalna, 2), "true_prob": true_prob,
                        "ev": round(ev_val, 3), "typ": typ, "kurs": kurs,
                        "l5": f"{pokrycie_l5}%", "l10": f"{pokrycie_l10}%",
                        "sezon": f"{int((sum(1 for x in vals if x > linia)/len(vals))*100)}%", "history": vals[-10:],
                        "uwagi": uwagi, "lokacja": "DOM" if is_today_home else "WYJ", "matchup_rank": m_rank,
                        "matchup_color": m_color, "opp_name": opp_name,
                        "is_value": is_value_bet, "is_safe": is_safe_bet, "is_stable": is_stable_bet, "is_graal": is_graal_bet
                    })

    wyniki = sorted(wyniki, key=lambda x: x['ev'], reverse=True)
    with open(MLB_JSON_FILE, 'w', encoding='utf-8') as f: json.dump(wyniki, f, ensure_ascii=False, indent=4)
    
    print(f"\n✅ Zakończono! Zapisano {len(wyniki)} typów.")
    top = [t for t in wyniki if t['ev'] > 0.05 and t['true_prob'] > 0.50][:5]
    if top:
        msg = "🚨 <b>RAPORT QUANT AI: MLB (PRO ULTIMATE v4.6)</b> 🚨\n\n"
        for t in top: 
            msg += f"⚾ {t['zawodnik']} - {t['rynek']}\n👉 <b>{t['typ']} {t['linia']}</b> @ {t['kurs']} (EV: +{round(t['ev']*100,1)}%)\n🤖 ML: {t['projekcja']} | {t['matchup_rank']}\n📈 L10: {list(reversed(t['history']))}\n\n"
        wyslij_powiadomienie_telegram(msg)
        
    wyslij_plik_na_githuba(MLB_JSON_FILE, "MLB Data: Update v4.6 (Culoodporny)")
    return wyniki

if __name__ == "__main__":
    uruchom_mlb_pro()
