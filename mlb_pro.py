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
CACHE_TEAM_K_RATE = {}
CACHE_ROSTERS = {}
LEAGUE_AVG_K_RATE = 0.225 

# 🏔️ PARK FACTORS (Efekt Stadionu) - > 1.0 faworyzuje pałkarzy, < 1.0 faworyzuje miotaczy
PARK_FACTORS = {
    'Colorado Rockies': 1.15, 'Cincinnati Reds': 1.12, 'Boston Red Sox': 1.08,
    'Atlanta Athletics': 1.05, 'Texas Rangers': 1.04, 'Chicago White Sox': 1.03,
    'Seattle Mariners': 0.90, 'San Diego Padres': 0.93, 'Oakland Athletics': 0.94,
    'Cleveland Guardians': 0.95, 'Tampa Bay Rays': 0.96, 'New York Mets': 0.96
}

# ==========================================
# NARZĘDZIA GITHUB / TELEGRAM
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

# ==========================================
# MATEMATYKA POISSONA
# ==========================================
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
                                "K's": p_stats.get('strikeOuts', 0), # <- NAPRAWIONY KLUCZ DLA MIOTACZY!
                                'Hits': b_stats.get('hits', 0),
                                'Home Runs': b_stats.get('homeRuns', 0),
                                'Total Bases': b_stats.get('totalBases', 0),
                                'Runs': b_stats.get('runs', 0),
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
        
        if not ma_kategorie and (typ.get('ev', 0) < 0.05 or typ.get('true_prob', 0) < 0.55): 
            continue
            
        zaw = typ['zawodnik'].lower().replace(".", "").replace("'", "").strip()
        rynek = typ['rynek']
        
        if zaw not in rzeczywiste_staty:
            historia.append({"zaklad": typ['zawodnik'], "wynik": "DNP/Przełożony", "status": "ZWROT"})
            zwroty += 1; continue
            
        wynik = rzeczywiste_staty[zaw].get(rynek, 0)
        czy_weszlo = (typ['typ'] == "OVER" and wynik > typ['linia']) or (typ['typ'] == "UNDER" and wynik < typ['linia'])
        
        if czy_weszlo: wygrane += 1; profit += (typ['kurs'] - 1.0); status = "✅ WYGRANA"
        else: przegrane += 1; profit -= 1.0; status = "❌ PRZEGRANA"
            
        is_value = typ.get('is_value', False)
        is_safe = typ.get('is_safe', False)
        is_stable = typ.get('is_stable', False)
        is_graal = typ.get('is_graal', False)
        
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
        print(f"✅ Raport MLB gotowy! Hit Rate: {hit_rate}%, ROI: {roi}% (Zysk: {round(profit,2)}u)")
        wyslij_plik_na_githuba(STATS_MLB_FILE, f"Auto-Raport Skuteczności MLB ({data_typow})")

# ==========================================
# 1. POBIERANIE Z OFICJALNEGO API MLB
# ==========================================
def pobierz_oficjalny_terminarz_mlb(data_str):
    print(f"⚾ Pobieram kalendarz, składy i line-upy na {data_str}...")
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={data_str}&hydrate=probablePitcher,lineups"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    baza_mlb = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        if 'dates' in res and len(res['dates']) > 0:
            mecze = res['dates'][0]['games']
            for m in mecze:
                home_team = m['teams']['home']['team']['name']
                away_team = m['teams']['away']['team']['name']
                
                home_team_id = m['teams']['home']['team']['id']
                away_team_id = m['teams']['away']['team']['id']
                
                home_p = m['teams']['home'].get('probablePitcher', {})
                away_p = m['teams']['away'].get('probablePitcher', {})
                
                home_p_hand = home_p.get('pitchHand', {}).get('code', 'R')
                away_p_hand = away_p.get('pitchHand', {}).get('code', 'R')
                
                lineups_home = {p['id']: i+1 for i, p in enumerate(m['teams']['home'].get('lineups', {}).get('homePlayers', []))}
                lineups_away = {p['id']: i+1 for i, p in enumerate(m['teams']['away'].get('lineups', {}).get('awayPlayers', []))}
                
                klucz_meczu = f"{away_team} @ {home_team}".lower().replace("st. ", "st ")
                
                baza_mlb[klucz_meczu] = {
                    'home_team': home_team, 'home_team_id': home_team_id,
                    'away_team': away_team, 'away_team_id': away_team_id,
                    'home_pitcher': home_p.get('fullName', 'TBD'), 'home_pitcher_id': home_p.get('id', None), 'home_pitcher_hand': home_p_hand,
                    'away_pitcher': away_p.get('fullName', 'TBD'), 'away_pitcher_id': away_p.get('id', None), 'away_pitcher_hand': away_p_hand,
                    'lineups_home': lineups_home, 'lineups_away': lineups_away,
                    'game_id': m['gamePk']
                }
    except Exception as e: print(f"❌ Błąd oficjalnego API MLB: {e}")
    return baza_mlb

def pobierz_roster(team_id):
    if not team_id: return {}
    if team_id in CACHE_ROSTERS: return CACHE_ROSTERS[team_id]
    
    time.sleep(0.05)
    url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster?hydrate=person"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    roster = {}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        for p in res.get('roster', []):
            name = p['person']['fullName'].lower().replace(".", "").replace("'", "").strip()
            bat_side = p['person'].get('batSide', {}).get('code', 'R')
            roster[name] = {'id': p['person']['id'], 'batSide': bat_side}
    except: pass
    
    CACHE_ROSTERS[team_id] = roster
    return roster

def pobierz_statystyki_druzyn_mlb():
    global LEAGUE_AVG_K_RATE
    print("📊 Pobieram statystyki (K-Rate przeciwników)...")
    url = f"https://statsapi.mlb.com/api/v1/teams/stats?season={SEZON_MLB - 1}&group=hitting&stats=season"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        stats = res.get('stats', [])
        if not stats: return
        
        splits = stats[0].get('splits', [])
        total_k, total_pa = 0, 0
        
        for team_data in splits:
            team_name = team_data['team']['name']
            k = team_data['stat'].get('strikeOuts', 0)
            pa = team_data['stat'].get('plateAppearances', 1)
            CACHE_TEAM_K_RATE[team_name] = k / pa if pa > 0 else 0
            total_k += k; total_pa += pa
            
        if total_pa > 0: LEAGUE_AVG_K_RATE = total_k / total_pa
    except: pass

def get_team_k_rate(team_name_odds):
    for mlb_name, k_rate in CACHE_TEAM_K_RATE.items():
        if mlb_name.lower() in team_name_odds.lower() or team_name_odds.lower() in mlb_name.lower():
            return k_rate
    return LEAGUE_AVG_K_RATE 

def pobierz_historie_gracza(player_id, typ_gracza, stat_key):
    if not player_id: return []
    cache_key = f"{player_id}_{stat_key}"
    if cache_key in CACHE_PLAYER_LOGS: return CACHE_PLAYER_LOGS[cache_key]
    
    time.sleep(0.05) 
    group = "pitching" if typ_gracza == "pitcher" else "hitting"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    historia_nowa = []
    historia_stara = []
    
    # 1. NAJPIERW POBIERAMY OBECNY SEZON
    try:
        url_nowy = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={SEZON_MLB}"
        res_nowy = requests.get(url_nowy, headers=headers, timeout=10).json()
        if 'stats' in res_nowy and len(res_nowy['stats']) > 0:
            for game in res_nowy['stats'][0].get('splits', []):
                stat_data = game.get('stat', {})
                if typ_gracza == "pitcher":
                    ip = float(stat_data.get('inningsPitched', '0.0'))
                    if ip >= 3.0: historia_nowa.append(stat_data.get('strikeOuts', 0))
                else:
                    ab = stat_data.get('atBats', 0)
                    if ab >= 2: historia_nowa.append(stat_data.get(stat_key, 0))
    except: pass

    # 2. JEŚLI MA MNIEJ NIŻ 15 MECZÓW W TYM SEZONIE, DOBIERAMY Z POPRZEDNIEGO
    if len(historia_nowa) < 15:
        try:
            url_stary = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats?stats=gameLog&group={group}&season={SEZON_MLB - 1}"
            res_stary = requests.get(url_stary, headers=headers, timeout=10).json()
            if 'stats' in res_stary and len(res_stary['stats']) > 0:
                for game in res_stary['stats'][0].get('splits', []):
                    stat_data = game.get('stat', {})
                    if typ_gracza == "pitcher":
                        ip = float(stat_data.get('inningsPitched', '0.0'))
                        if ip >= 3.0: historia_stara.append(stat_data.get('strikeOuts', 0))
                    else:
                        ab = stat_data.get('atBats', 0)
                        if ab >= 2: historia_stara.append(stat_data.get(stat_key, 0))
        except: pass

    # Łączymy historię: stara baza + świeżutkie mecze na samym końcu (L5 pokaże najnowsze!)
    historia_pelna = historia_stara + historia_nowa
    
    CACHE_PLAYER_LOGS[cache_key] = historia_pelna
    return historia_pelna

# ==========================================
# 2. GŁÓWNA PĘTLA
# ==========================================
def uruchom_mlb_pro():
    print("==================================================")
    print("🚀 START: QUANT AI BOTS (MLB PRO - ULTIMATE v3)")
    print("==================================================")
    
    # --- ROZWIĄZANIE PROBLEMU PIERWSZEGO DNIA ---
    if not os.path.exists(STATS_MLB_FILE):
        with open(STATS_MLB_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
        wyslij_plik_na_githuba(STATS_MLB_FILE, "Inicjalizacja pustego pliku statystyk MLB")
        print("✅ Wymuszono utworzenie pustego pliku statystyk na GitHubie!")
    # --------------------------------------------
    
    rozlicz_wczorajsze_typy_mlb()
    pobierz_statystyki_druzyn_mlb()
    baza_mlb = pobierz_oficjalny_terminarz_mlb(DATA_DZIS)
    
    print("📡 Pobieram kursy (The Odds API)...")
    try:
        url_odds = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={ODDS_API_KEY}"
        events = requests.get(url_odds).json()
        
        # 🛡️ Przywrócona Tarcza Ochronna
        if isinstance(events, dict) and 'message' in events:
            print(f"❌ ODRZUCONO ZAPYTANIE (The Odds API): {events['message']}")
            return []
            
    except Exception as e:
        print(f"❌ BŁĄD POŁĄCZENIA: {e}")
        return []

    if not isinstance(events, list):
        print(f"❌ Nieoczekiwana odpowiedź od The Odds API (Zła struktura danych).")
        return []

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

    for i, ev in enumerate(mecze_dzis, 1):
        away_team = ev['away_team']
        home_team = ev['home_team']
        m_str = f"{away_team} @ {home_team}"
        
        klucz_szukania = m_str.lower().replace("st. ", "st ")
        dane_oficjalne = baza_mlb.get(klucz_szukania, {})
        
        if not dane_oficjalne: continue
        
        home_p_name, home_p_id, home_p_hand = dane_oficjalne.get('home_pitcher'), dane_oficjalne.get('home_pitcher_id'), dane_oficjalne.get('home_pitcher_hand')
        away_p_name, away_p_id, away_p_hand = dane_oficjalne.get('away_pitcher'), dane_oficjalne.get('away_pitcher_id'), dane_oficjalne.get('away_pitcher_hand')
        
        home_roster = pobierz_roster(dane_oficjalne.get('home_team_id'))
        away_roster = pobierz_roster(dane_oficjalne.get('away_team_id'))
        
        try:
            res_odds = requests.get(f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal").json()
        except: continue
        
        for bm in res_odds.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                market_key = mkt['key']
                if market_key not in rynek_map: continue
                
                nazwa_rynku_pl, rola, mlb_stat_key = rynek_map[market_key]
                
                for oc in mkt['outcomes']:
                    p_name = oc['description']
                    linia = oc['point']
                    kurs = oc['price']
                    
                    if oc['name'] != 'Over': continue
                    
                    # 🛠️ WYMUSZENIE LINII 1.5 DLA RBI (Zgodnie z ofertą Twojego bukmachera)
                    if mlb_stat_key == 'totalBases':
                        linia = 1.5
                    elif mlb_stat_key == 'hits':
                        linia = 0.5
                    
                    unikalny_klucz = f"{p_name}_{market_key}"
                    if unikalny_klucz in przetworzeni_zawodnicy: continue
                    przetworzeni_zawodnicy.add(unikalny_klucz)
                    
                    czysta_nazwa_buka = p_name.lower().replace(".", "").replace("'", "").strip()
                    
                    player_id = None; lokacja = "DOM"; opp_name = away_team; bat_side = 'R'
                    batting_order = 0
                    
                    if rola == 'pitcher':
                        home_clean = home_p_name.lower().replace(".", "").replace("'", "").strip()
                        away_clean = away_p_name.lower().replace(".", "").replace("'", "").strip()
                        if czysta_nazwa_buka in home_clean or home_clean in czysta_nazwa_buka:
                            player_id = home_p_id; lokacja = "DOM"; opp_name = away_team
                        elif czysta_nazwa_buka in away_clean or away_clean in czysta_nazwa_buka:
                            player_id = away_p_id; lokacja = "WYJ"; opp_name = home_team
                    else: 
                        if czysta_nazwa_buka in home_roster:
                            player_id = home_roster[czysta_nazwa_buka]['id']
                            bat_side = home_roster[czysta_nazwa_buka]['batSide']
                            lokacja = "DOM"; opp_name = away_team
                            batting_order = dane_oficjalne.get('lineups_home', {}).get(player_id, 0)
                        elif czysta_nazwa_buka in away_roster:
                            player_id = away_roster[czysta_nazwa_buka]['id']
                            bat_side = away_roster[czysta_nazwa_buka]['batSide']
                            lokacja = "WYJ"; opp_name = home_team
                            batting_order = dane_oficjalne.get('lineups_away', {}).get(player_id, 0)
                    
                    if not player_id: continue
                    
                    historia = pobierz_historie_gracza(player_id, rola, mlb_stat_key)
                    if not historia: continue
                    
                    l15_historia = historia[-15:]
                    baza_proj = sum(l15_historia) / len(l15_historia)
                    
                    # ---------------------------------------------------------
                    # 🧠 POTĘŻNE MODYFIKATORY (DVP, PARK FACTORS, L/R SPLITS)
                    # ---------------------------------------------------------
                    korekta = 1.0 
                    uwagi = f"⚾ Baza L15: {round(baza_proj,2)}."
                    m_color = "rank-yellow"
                    m_rank = "Neutral"
                    
                    if rola == 'pitcher':
                        opp_k_rate = get_team_k_rate(opp_name)
                        korekta = max(0.85, min(1.15, opp_k_rate / LEAGUE_AVG_K_RATE if LEAGUE_AVG_K_RATE > 0 else 1.0))
                        opp_pct_str = f"{round(opp_k_rate * 100, 1)}%"
                        if korekta >= 1.03: m_color = "rank-green"; m_rank = f"Wiatraki: {opp_pct_str}"
                        elif korekta <= 0.97: m_color = "rank-red"; m_rank = f"Trudny: {opp_pct_str}"
                        uwagi += f" Rywal K%: {opp_pct_str}."
                    
                    else:
                        # 1. Park Factor
                        pf = PARK_FACTORS.get(home_team, 1.0)
                        if pf != 1.0:
                            if mlb_stat_key == 'homeRuns': pf = ((pf - 1.0) * 1.5) + 1.0 
                            korekta *= pf
                            uwagi += f" 🏟️ Stadion PF: {round(pf, 2)}x."
                        
                        # 2. L/R Splits (Przewaga Ręki)
                        p_hand = home_p_hand if lokacja == 'WYJ' else away_p_hand
                        if p_hand and bat_side:
                            if bat_side == 'S': 
                                korekta *= 1.04; uwagi += " ⚔️ Switch Hitter (+4%)."
                            elif bat_side != p_hand: 
                                korekta *= 1.08; uwagi += f" ⚔️ Platoon Adv ({bat_side} vs {p_hand}) (+8%)."
                                m_color = "rank-green"; m_rank = "Świetny Split"
                            else: 
                                korekta *= 0.95; uwagi += f" ⚔️ Hard Split ({bat_side} vs {p_hand}) (-5%)."
                                m_color = "rank-red"; m_rank = "Zły Split"
                                
                        # 3. Lineup Order (Im wyżej w składzie, tym więcej podejść)
                        if batting_order > 0:
                            if batting_order <= 3: korekta *= 1.05; uwagi += f" 📋 Batting #{batting_order} (+5%)."
                            elif batting_order >= 8: korekta *= 0.90; uwagi += f" 📋 Batting #{batting_order} (-10%)."
                    
                    projekcja_finalna = baza_proj * korekta
                    
                    prob_over = poisson_prob_over(projekcja_finalna, linia)
                    
                    # Wymuszony OVER dla Home Runów
                    if mlb_stat_key == 'homeRuns':
                        typ = "OVER"
                    else:
                        typ = "OVER" if prob_over > 0.50 else "UNDER"
                        
                    true_prob = prob_over if typ == "OVER" else (1.0 - prob_over)
                    obliczeniowy_kurs = kurs if typ == "OVER" else 1.85 
                    ev_val = (true_prob * obliczeniowy_kurs) - 1.0
                    
                    pokrycie_l5 = int((sum(1 for x in historia[-5:] if x > linia) / 5) * 100) if len(historia) >= 5 else 0
                    pokrycie_l10 = int((sum(1 for x in historia[-10:] if x > linia) / 10) * 100) if len(historia) >= 10 else 0
                    pokrycie_sezon = int((sum(1 for x in historia if x > linia) / len(historia)) * 100)
                    
                    # 🏷️ TRWAŁE ZNAKOWANIE (Stemplowanie) TYPÓW MLB!
                    is_value_bet = ev_val >= 0.04
                    is_safe_bet = true_prob >= 0.75 and pokrycie_l5 >= 80
                    is_stable_bet = (m_color == "rank-green")
                    is_graal_bet = is_value_bet and is_safe_bet and is_stable_bet
                    
                    print(f"✅ Skan: {p_name:<18} | {nazwa_rynku_pl:<15} | Proj: {round(projekcja_finalna,1)} | Szansa: {round(true_prob*100,1)}%")
                    
                    wyniki.append({
                        "zawodnik": p_name,
                        "mecz": m_str,
                        "data": DATA_DZIS, # <--- ZNACZNIK DATY DLA AUDYTORA
                        "rynek": nazwa_rynku_pl,
                        "linia": linia,
                        "projekcja": round(projekcja_finalna, 2),
                        "true_prob": true_prob,
                        "ev": round(ev_val, 3),
                        "typ": typ,
                        "kurs": obliczeniowy_kurs,
                        "l5": f"{pokrycie_l5}%",
                        "l10": f"{pokrycie_l10}%",
                        "sezon": f"{pokrycie_sezon}%",
                        "history": historia[-10:],
                        "uwagi": uwagi,
                        "lokacja": lokacja,
                        "matchup_rank": m_rank,
                        "matchup_color": m_color,
                        "opp_name": opp_name,
                        "is_value": is_value_bet,
                        "is_safe": is_safe_bet,
                        "is_stable": is_stable_bet,
                        "is_graal": is_graal_bet
                    })

    wyniki = sorted(wyniki, key=lambda x: x['ev'], reverse=True)
    with open(MLB_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(wyniki, f, ensure_ascii=False, indent=4)
        
    print(f"\n✅ Gotowe! Wyliczono {len(wyniki)} zoptymalizowanych matematycznie projekcji MLB.")
    
    # 🌟 Raport Telegram na najlepsze Value Bety!
    top = [t for t in wyniki if t['ev'] > 0.05 and t['true_prob'] > 0.50][:5]
    if top:
        msg = "🚨 <b>RAPORT QUANT AI: MLB (PRO ULTIMATE)</b> 🚨\n\n"
        for t in top: 
            msg += f"⚾ {t['zawodnik']} - {t['rynek']}\n"
            msg += f"👉 <b>{t['typ']} {t['linia']}</b> @ {t['kurs']} (EV: +{round(t['ev'] * 100, 1)}%)\n"
            msg += f"🤖 ML: {t['projekcja']} | {t['matchup_rank']}\n"
            msg += f"📈 L10: {list(reversed(t['history']))}\n\n"
        wyslij_powiadomienie_telegram(msg)
        print("📲 Wysłano raport na Telegram!")
        
    wyslij_plik_na_githuba(MLB_JSON_FILE, "Aktualizacja bazy MLB (v3)")
    return wyniki

if __name__ == "__main__":
    uruchom_mlb_pro()
