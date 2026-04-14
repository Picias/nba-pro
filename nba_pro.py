import requests
import json
import time
import math
import base64
import os
from datetime import datetime, timedelta
from sklearn.linear_model import Ridge
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
SPORTS_API_KEY = os.environ.get('MY_SPORTS_API_KEY')

SPORT = 'basketball_nba'
REGIONS = 'us'
MARKETS = 'player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists,spreads,totals'
SEZON_NBA = 2025
SMART_MONEY_FILE = 'smart_money.json'
STATS_FILE = 'statystyki_bota.json'
ODDS_CACHE_FILE = 'odds_cache.json'
ODDS_CACHE_EXPIRY = 3600 

HEADERS_SPORTS = {
    'x-apisports-key': SPORTS_API_KEY,
    'x-rapidapi-host': 'v2.nba.api-sports.io'
}

# ==========================================
# PAMIĘĆ PODRĘCZNA (CACHE)
# ==========================================
CACHE_ROSTERS = {}
CACHE_DVP = {}
CACHE_PLAYER_STATS = {}
CACHE_TEAM_GAMES = {}
CACHE_GAME_STATS = {}
CACHE_INJURIES = {}
CACHE_RAW_GAME_STATS = {} # 🚀 NOWOŚĆ: Główny magazyn zaciągniętych statystyk meczowych
NBA_TEAMS = {}

L_AVG_3PM = 12.8
L_AVG_REB = 43.5

# ==========================================
# FUNKCJE POMOCNICZE I OPTYMALIZACJA API
# ==========================================
def get_stat_val(z, stat_key):
    if stat_key == 'PTS': return z.get('points', 0) or 0
    if stat_key == 'REB': return z.get('totReb', 0) or 0
    if stat_key == 'AST': return z.get('assists', 0) or 0
    if stat_key == '3PM': return z.get('tpm', 0) or 0
    if stat_key == 'PRA': return (z.get('points', 0) or 0) + (z.get('totReb', 0) or 0) + (z.get('assists', 0) or 0)
    return 0

# 🚀 NOWOŚĆ: JEDNA FUNKCJA BY RZĄDZIĆ WSZYSTKIMI MECZAMI (Chroni API przed wyczerpaniem limitów)
def pobierz_surowe_staty_meczu(game_id):
    g_str = str(game_id)
    if g_str in CACHE_RAW_GAME_STATS: return CACHE_RAW_GAME_STATS[g_str]
    
    time.sleep(0.15) # Bezpieczny timing (ok. 6 zapytań/sek)
    try:
        url = f"https://v2.nba.api-sports.io/players/statistics?game={g_str}"
        res = requests.get(url, headers=HEADERS_SPORTS).json()
        
        if 'errors' in res and res['errors']:
            print(f"⚠️ API Limit/Błąd (Gra {g_str}): {res['errors']}")
            return []
            
        dane = res.get('response', [])
        if dane: # Zapisujemy do RAMu tylko, jeśli dane są prawidłowe (zabezpieczenie przed zatruciem cache'a!)
            CACHE_RAW_GAME_STATS[g_str] = dane
        return dane
    except Exception as e:
        return []

def inicjalizuj_druzyny():
    print("📡 Synchronizuję oficjalne ID drużyn z bazą API-Sports...")
    try:
        url = "https://v2.nba.api-sports.io/teams"
        res = requests.get(url, headers=HEADERS_SPORTS)
        data = res.json()
        
        if 'errors' in data and data['errors']:
            print(f"❌ BŁĄD API-SPORTS: {data['errors']}")
            
        for t in data.get('response', []):
            name = t.get('name')
            t_id = t.get('id')
            if name and t_id: NBA_TEAMS[name] = t_id
            
        if "LA Clippers" in NBA_TEAMS: 
            NBA_TEAMS["Los Angeles Clippers"] = NBA_TEAMS["LA Clippers"]
            NBA_TEAMS["L.A. Clippers"] = NBA_TEAMS["LA Clippers"]
            
        print(f"✅ Baza drużyn gotowa! Wczytano {len(NBA_TEAMS)} zespołów.\n")
    except Exception as e: 
        print(f"❌ KRYTYCZNY BŁĄD POŁĄCZENIA: {e}")

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

def parse_min(min_str):
    if not min_str or str(min_str) == "0": return 0.0
    try:
        if ":" in str(min_str): m, s = map(int, str(min_str).split(':')); return m + (s / 60.0)
        return float(min_str)
    except: return 0.0

# ==========================================
# 📊 MODUŁ AUTO-ROZLICZEŃ (AUDYTOR NBA)
# ==========================================
def rozlicz_wczorajsze_typy():
    try:
        with open('nba.json', 'r', encoding='utf-8') as f: stare_typy = json.load(f)
    except: return

    if not stare_typy: return
    data_typow = stare_typy[0].get('data')
    dzisiaj = datetime.now().strftime('%Y-%m-%d')
    
    if not data_typow or data_typow >= dzisiaj: return
        
    print(f"🕵️ Uruchamiam Audytora: Rozliczam typy z wczoraj ({data_typow})...")
    try:
        time.sleep(0.15)
        res_games = requests.get(f"https://v2.nba.api-sports.io/games?date={data_typow}", headers=HEADERS_SPORTS).json()
        mecze = res_games.get('response', [])
    except: return
        
    rzeczywiste_staty = {}
    for m in mecze:
        if m['status']['long'] == 'Finished':
            dane = pobierz_surowe_staty_meczu(m['id'])
            for z in dane:
                p_info = z.get('player', {})
                full_n = f"{str(p_info.get('firstname', '')).strip()} {str(p_info.get('lastname', '')).strip()}".lower().replace(".", "").replace("'", "").strip()
                rzeczywiste_staty[full_n] = {
                    'PTS': get_stat_val(z, 'PTS'), 'REB': get_stat_val(z, 'REB'),
                    'AST': get_stat_val(z, 'AST'), '3PM': get_stat_val(z, '3PM'),
                    'PRA': get_stat_val(z, 'PRA'), 'MIN': parse_min(z.get('min', '0'))
                }
            
    wygrane = przegrane = zwroty = 0
    profit = 0.0
    historia = []
    kategorie = {"graal": {"w": 0, "t": 0}, "value": {"w": 0, "t": 0}, "safe": {"w": 0, "t": 0}, "stable": {"w": 0, "t": 0}}
    
    for typ in stare_typy:
        ma_kategorie = typ.get('is_graal', False) or typ.get('is_value', False) or typ.get('is_safe', False) or typ.get('is_stable', False)
        if not ma_kategorie and (typ.get('ev', 0) < 0.05 or typ.get('true_prob', 0) < 0.55): continue
            
        zaw = typ['zawodnik'].lower().replace(".", "").replace("'", "").strip()
        r_pl = typ['rynek']
        
        s_key = 'PTS' if 'PTS' in r_pl else 'REB' if 'REB' in r_pl else 'AST' if 'AST' in r_pl else '3PM' if '3PM' in r_pl else 'PRA' if 'PRA' in r_pl else None
        if not s_key: continue
        
        znaleziony = next((k for k in rzeczywiste_staty.keys() if zaw in k or k in zaw), None)
                
        if znaleziony:
            wynik = rzeczywiste_staty[znaleziony][s_key]
            minuty = rzeczywiste_staty[znaleziony]['MIN']
            
            if minuty == 0:
                historia.append({"zaklad": typ['zawodnik'], "wynik": "DNP", "status": "ZWROT"})
                zwroty += 1; continue
                
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
                
            historia.append({"zawodnik": typ['zawodnik'], "rynek": r_pl, "typ": typ['typ'], "linia": typ['linia'], "wynik_realny": wynik, "kurs": typ['kurs'], "status": status, "kategoria": " | ".join(etykiety) if etykiety else "Zwykły Typ"})
            
    suma = wygrane + przegrane
    if suma > 0:
        hit_rate = round((wygrane / suma) * 100, 1); roi = round((profit / suma) * 100, 1)
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f: baza_stat = json.load(f)
        except: baza_stat = []
        baza_stat = [r for r in baza_stat if r['data_meczow'] != data_typow]
        baza_stat.insert(0, {"data_meczow": data_typow, "wygrane": wygrane, "przegrane": przegrane, "zwroty": zwroty, "hit_rate": f"{hit_rate}%", "profit_jednostki": round(profit, 2), "roi": f"{roi}%", "kategorie": kategorie, "detale": historia})
        with open(STATS_FILE, 'w', encoding='utf-8') as f: json.dump(baza_stat, f, ensure_ascii=False, indent=4)
        print(f"✅ Raport NBA gotowy! Hit Rate: {hit_rate}%, ROI: {roi}% (Zysk: {round(profit,2)}u)")
        wyslij_plik_na_githuba(STATS_FILE, f"Auto-Raport NBA ({data_typow})")

# ==========================================
# POZOSTAŁE FUNKCJE API I ML 
# ==========================================
def pobierz_kalendarz_druzyny(team_id):
    if team_id in CACHE_TEAM_GAMES: return CACHE_TEAM_GAMES[team_id]
    time.sleep(0.15)
    try:
        res = requests.get(f"https://v2.nba.api-sports.io/games?team={team_id}&season={SEZON_NBA}", headers=HEADERS_SPORTS).json()
        kalendarz = {}
        for m in res.get('response', []):
            g_id = m['id']
            home_id = m['teams']['home']['id']
            away_id = m['teams']['visitors']['id']
            opp_id = away_id if home_id == team_id else home_id
            kalendarz[g_id] = {'date': m['date']['start'], 'opp': opp_id, 'is_home': home_id == team_id}
        CACHE_TEAM_GAMES[team_id] = kalendarz
        return kalendarz
    except: return {}

def pobierz_dzisiejsze_kontuzje():
    if "dzis" in CACHE_INJURIES: return CACHE_INJURIES["dzis"]
    kontuzje_druzyn = {}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        url = "https://www.cbssports.com/nba/injuries/"
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        zespoly_sekcje = soup.find_all('div', class_='TableBaseWrapper')

        for sekcja in zespoly_sekcje:
            tytul_sekcji = sekcja.find(class_='TableBase-title')
            if not tytul_sekcji: continue 
                
            team_tag = tytul_sekcji.find('span', class_='TeamName')
            if not team_tag: continue
                
            team_name_raw = team_tag.text.strip()
            team_id = None
            
            for nazwa_nasza, id_nasze in NBA_TEAMS.items():
                if team_name_raw in nazwa_nasza or nazwa_nasza in team_name_raw:
                    team_id = id_nasze
                    break
                    
            if not team_id: continue
            if team_id not in kontuzje_druzyn: kontuzje_druzyn[team_id] = []

            wiersze = sekcja.find_all('tr', class_='TableBase-bodyTr')
            for w in wiersze:
                kolumny = w.find_all('td')
                if len(kolumny) >= 5:
                    gracz_tag = kolumny[0].find('span', class_='CellPlayerName--long')
                    status_tag = kolumny[4] 
                    if gracz_tag and status_tag:
                        nazwisko = gracz_tag.text.strip()
                        status = status_tag.text.strip().lower()
                        if 'out' in status or 'expected to be out' in status:
                            kontuzje_druzyn[team_id].append(nazwisko)

        CACHE_INJURIES["dzis"] = kontuzje_druzyn
        return kontuzje_druzyn
    except Exception as e: 
        return {}

def pobierz_id_i_pozycje(nazwa_gracza, team_name):
    team_id = NBA_TEAMS.get(team_name)
    if not team_id: return None, None
    if team_id not in CACHE_ROSTERS:
        time.sleep(0.15)
        url = f"https://v2.nba.api-sports.io/players?team={team_id}&season={SEZON_NBA}"
        try:
            res = requests.get(url, headers=HEADERS_SPORTS).json()
            if 'errors' in res and res['errors']:
                print(f"⚠️ API Błąd Roster: {res['errors']}")
            zawodnicy = res.get('response', [])
            
            if not zawodnicy:
                time.sleep(0.15)
                res_fb = requests.get(f"https://v2.nba.api-sports.io/players?team={team_id}&season={SEZON_NBA - 1}", headers=HEADERS_SPORTS).json()
                zawodnicy = res_fb.get('response', [])
                
            if zawodnicy: # Zapisujemy tylko jeśli cokolwiek zwróciło
                CACHE_ROSTERS[team_id] = zawodnicy
        except: return None, None
        
    czysta_nazwa = nazwa_gracza.lower().replace(".", "").replace("'", "").strip()
    for p in CACHE_ROSTERS.get(team_id, []):
        f_name = str(p.get('firstname', '')).strip()
        l_name = str(p.get('lastname', '')).strip()
        full_name = f"{f_name} {l_name}".lower().replace(".", "").replace("'", "").strip()
        if len(full_name) < 3: continue
        if czysta_nazwa == full_name or full_name in czysta_nazwa:
            pozycja = 'F'
            try: leagues = p.get('leagues'); pozycja = leagues['standard'].get('pos', 'F') if leagues and 'standard' in leagues else 'F'; pozycja = 'F' if not pozycja else pozycja
            except: pass
            return p['id'], pozycja[0]
    return None, None

def pobierz_staty_meczu_global(game_id):
    if game_id in CACHE_GAME_STATS: return CACHE_GAME_STATS[game_id]
    
    dane = pobierz_surowe_staty_meczu(game_id)
    if not dane: return None
    
    teams = {}
    for z in dane:
        t_id = z['team']['id']
        if t_id not in teams: teams[t_id] = {'FGA':0, 'FTA':0, 'TOV':0, 'MIN':0.0, 'PLAYERS': set()}
        minuty = parse_min(z.get('min', '0'))
        teams[t_id]['FGA'] += z.get('fga', 0) or 0
        teams[t_id]['FTA'] += z.get('fta', 0) or 0
        teams[t_id]['TOV'] += z.get('turnovers', 0) or 0
        teams[t_id]['MIN'] += minuty
        if minuty > 0:
            p_info = z.get('player', {})
            full_n = f"{str(p_info.get('firstname', '')).strip()} {str(p_info.get('lastname', '')).strip()}".lower().replace(".", "").replace("'", "").strip()
            teams[t_id]['PLAYERS'].add(full_n)
            
    CACHE_GAME_STATS[game_id] = teams
    return teams

def pobierz_dvp_i_obrone(opp_team_id, pozycja, stat_key, is_leader, limit_meczow=7):
    cache_key = f"{opp_team_id}_{pozycja}_{stat_key}_{is_leader}"
    if cache_key in CACHE_DVP: return CACHE_DVP[cache_key]
    
    bazy = {
        'G': {'PTS': 16.0, 'REB': 4.0, 'AST': 5.0, '3PM': 1.5, 'PRA': 25.0},
        'F': {'PTS': 15.0, 'REB': 6.0, 'AST': 3.0, '3PM': 1.2, 'PRA': 24.0},
        'C': {'PTS': 14.0, 'REB': 9.0, 'AST': 2.0, '3PM': 0.3, 'PRA': 25.0}
    }
    poz_baza = bazy.get(pozycja, bazy['F'])
    domyslne_dvp = poz_baza.get(stat_key, 10.0)
    
    time.sleep(0.15)
    try:
        res_games = requests.get(f"https://v2.nba.api-sports.io/games?team={opp_team_id}&season={SEZON_NBA}", headers=HEADERS_SPORTS).json()
        mecze_zakonczone = sorted([m for m in res_games.get('response', []) if m['status']['long'] == 'Finished'], key=lambda x: x['date']['start'])
    except: return domyslne_dvp, L_AVG_3PM, L_AVG_REB 
    
    suma_stat = 0; przeanalizowane = 0
    total_3pm = 0; total_reb = 0
    
    for mecz in reversed(mecze_zakonczone):
        if przeanalizowane >= limit_meczow: break
        game_id = mecz['id']
        opp_id = mecz['teams']['visitors']['id'] if mecz['teams']['home']['id'] == opp_team_id else mecz['teams']['home']['id']
        
        dane = pobierz_surowe_staty_meczu(game_id)
        if not dane: continue
        
        gracze_na_pozycji = []
        game_3pm = 0; game_reb = 0
        
        for z in dane:
            if z['team']['id'] == opp_id:
                game_3pm += get_stat_val(z, '3PM')
                game_reb += get_stat_val(z, 'REB')
                
                pos = z.get('pos'); minuty = parse_min(z.get('min'))
                if pos and pozycja in pos and minuty > 5.0:
                    val = get_stat_val(z, stat_key)
                    gracze_na_pozycji.append({'val': val or 0, 'min': minuty})
                    
        if gracze_na_pozycji:
            gracze_na_pozycji.sort(key=lambda x: x['min'], reverse=True)
            suma_stat += gracze_na_pozycji[0]['val'] if is_leader else (gracze_na_pozycji[1]['val'] if len(gracze_na_pozycji) > 1 else gracze_na_pozycji[0]['val'])
            total_3pm += game_3pm
            total_reb += game_reb
            przeanalizowane += 1
            
    wynik_dvp = round(suma_stat / przeanalizowane, 1) if przeanalizowane > 0 else domyslne_dvp
    avg_3pm = total_3pm / przeanalizowane if przeanalizowane > 0 else L_AVG_3PM
    avg_reb = total_reb / przeanalizowane if przeanalizowane > 0 else L_AVG_REB
    
    CACHE_DVP[cache_key] = (wynik_dvp, avg_3pm, avg_reb)
    return CACHE_DVP[cache_key]

def przeanalizuj_gracza_ml(player_id, nazwa, pozycja, stat_key, team_id, opp_team_id, linia, data_dzis, team_spread, game_total, is_home_game):
    cache_key = f"stats_{player_id}"
    
    if cache_key in CACHE_PLAYER_STATS: 
        response_data = CACHE_PLAYER_STATS[cache_key]
    else:
        time.sleep(0.15)
        try:
            res_json = requests.get(f"https://v2.nba.api-sports.io/players/statistics?season={SEZON_NBA}&id={player_id}", headers=HEADERS_SPORTS).json()
            if 'errors' in res_json and res_json['errors']:
                return None, f"⚠️ API Limit: {res_json['errors']}"
                
            response_data = res_json.get('response', [])
            if response_data:
                CACHE_PLAYER_STATS[cache_key] = response_data
        except Exception as e: return None, f"Błąd połącz.: {e}"
            
    if not response_data: return None, "Brak historii"
    
    kalendarz = pobierz_kalendarz_druzyny(team_id)
    mecze_sezon = [m for m in response_data if parse_min(m.get('min')) > 5.0]
    mecze_sezon = sorted(mecze_sezon, key=lambda x: kalendarz.get(x['game']['id'], {}).get('date', '1970-01-01'))
    
    if len(mecze_sezon) < 5: return None, f"Za mało meczów ({len(mecze_sezon)})"
    
    X, y, wszystkie_statystyki = [], [], []
    usg_list, pace_list, h2h_stats, split_stats = [], [], [], []
    
    all_mins = [parse_min(m.get('min')) for m in mecze_sezon]
    season_avg_min = sum(all_mins) / len(all_mins) if all_mins else 30.0
    
    for m in mecze_sezon:
        g_id = m['game']['id']
        minuty = parse_min(m.get('min'))
        val = get_stat_val(m, stat_key)
        
        if kalendarz.get(g_id, {}).get('is_home') == is_home_game: split_stats.append(val)
        if kalendarz.get(g_id, {}).get('opp') == opp_team_id: h2h_stats.append(val)
            
        X.append([minuty])
        y.append(val)
        wszystkie_statystyki.append(val)

        if m in mecze_sezon[-5:]:
            box = pobierz_staty_meczu_global(g_id)
            if box and team_id in box:
                t_stats = box[team_id]
                p_fga, p_fta, p_tov = m.get('fga', 0) or 0, m.get('fta', 0) or 0, m.get('turnovers', 0) or 0
                if minuty > 0 and t_stats['MIN'] > 0:
                    licznik = (p_fga + 0.44 * p_fta + p_tov) * (t_stats['MIN'] / 5)
                    mianownik = minuty * (t_stats['FGA'] + 0.44 * t_stats['FTA'] + t_stats['TOV'])
                    if mianownik > 0: usg_list.append((licznik / mianownik) * 100)
                if t_stats['MIN'] > 0:
                    pace_list.append(48.0 * ((t_stats['FGA'] + 0.44 * t_stats['FTA'] + t_stats['TOV']) / (t_stats['MIN'] / 5)))

    l10_stats = wszystkie_statystyki[-10:] if len(wszystkie_statystyki) >= 10 else wszystkie_statystyki
    
    l5_mins_raw = [parse_min(m.get('min')) for m in mecze_sezon[-5:]]
    true_l5_mins = [m if abs(m - season_avg_min) <= 8 else season_avg_min for m in l5_mins_raw]
    avg_min_l5 = sum(true_l5_mins) / len(true_l5_mins) if true_l5_mins else 30.0
    is_leader = True if season_avg_min >= 26.0 else False
    
    if is_leader:
        avg_min_l5 = min(42.0, avg_min_l5 * 1.08)

    dzis_date = datetime.strptime(data_dzis, '%Y-%m-%d')
    prev_dates = []
    for g_info in kalendarz.values():
        try:
            g_d = datetime.strptime(g_info['date'][:10], '%Y-%m-%d')
            if g_d < dzis_date: prev_dates.append(g_d)
        except: pass
    
    fatigue_multi = 1.0
    is_b2b = False
    if prev_dates:
        rest_days = (dzis_date - max(prev_dates)).days - 1
        if rest_days == 0: 
            fatigue_multi = 0.95 
            is_b2b = True
            
    blowout_multi = 1.0
    is_blowout = False
    if is_leader and abs(team_spread) >= 13.0:
        blowout_multi = 0.85 
        is_blowout = True

    model = Ridge(alpha=1.0).fit(X[-15:], y[-15:])
    proj_baza = model.predict([[avg_min_l5]])[0]

    korekta_kontuzji = 1.0
    on_off_text = ""
    absencje_wplywajace = []
    oficjalne_nazwy_wplywajace = []
    kontuzje = pobierz_dzisiejsze_kontuzje()
    lista_out = kontuzje.get(team_id, [])
    
    if lista_out:
        roster = CACHE_ROSTERS.get(team_id, [])
        for inj_name in lista_out:
            czysta_nazwa_inj = inj_name.lower().replace(".", "").replace("'", "").strip()
            inj_pos, oficjalna_nazwa_inj = None, None
            for p in roster:
                f_name = f"{p.get('firstname', '')} {p.get('lastname', '')}".lower().replace(".", "").replace("'", "").strip()
                if len(f_name) > 2 and (czysta_nazwa_inj == f_name or f_name in czysta_nazwa_inj or czysta_nazwa_inj in f_name):
                    try: inj_pos = p['leagues']['standard']['pos'][0]
                    except: pass
                    oficjalna_nazwa_inj = f_name
                    break
            
            if inj_pos and oficjalna_nazwa_inj:
                gral_ostatnio = False
                for m in mecze_sezon[-5:]:
                    box = pobierz_staty_meczu_global(m['game']['id'])
                    if box and team_id in box and oficjalna_nazwa_inj in box[team_id]['PLAYERS']:
                        gral_ostatnio = True; break
                
                if gral_ostatnio:
                    czy_obwod = pozycja == 'G' and inj_pos == 'G'
                    czy_pomalowane = pozycja in ['F', 'C'] and inj_pos in ['F', 'C']
                    if czy_obwod or czy_pomalowane:
                        absencje_wplywajace.append(inj_name)
                        oficjalne_nazwy_wplywajace.append(oficjalna_nazwa_inj)
                        
        if absencje_wplywajace:
            glowny_nieobecny = oficjalne_nazwy_wplywajace[0]
            on_off_stats = []
            for m in mecze_sezon:
                box = pobierz_staty_meczu_global(m['game']['id'])
                if box and team_id in box and glowny_nieobecny not in box[team_id]['PLAYERS']:
                    val = get_stat_val(m, stat_key)
                    on_off_stats.append(val or 0)
            
            if len(on_off_stats) >= 3:
                on_off_avg = sum(on_off_stats) / len(on_off_stats)
                ratio = on_off_avg / proj_baza if proj_baza > 0 else 1.2
                korekta_kontuzji = max(0.8, min(1.3, ratio))
                on_off_text = f" (Śr. bez niego: {round(on_off_avg, 1)})"
            
    avg_usg = round(sum(usg_list) / len(usg_list), 1) if usg_list else 20.0
    avg_pace = round(sum(pace_list) / len(pace_list), 1) if pace_list else 100.0
    
    dvp, opp_3pm_allowed, opp_reb_allowed = pobierz_dvp_i_obrone(opp_team_id, pozycja, stat_key, is_leader)
    
    standardy_ligowe = {
        'G': {'PTS': 16.0, 'REB': 4.0, 'AST': 5.0, '3PM': 1.5, 'PRA': 25.0}, 
        'F': {'PTS': 15.0, 'REB': 6.0, 'AST': 3.0, '3PM': 1.2, 'PRA': 24.0}, 
        'C': {'PTS': 14.0, 'REB': 9.0, 'AST': 2.0, '3PM': 0.3, 'PRA': 25.0} 
    }
    
    baza_pozycji = standardy_ligowe.get(pozycja, standardy_ligowe['F'])
    baza_dvp = baza_pozycji.get(stat_key, 10.0)
    
    roznica_w_procentach = (dvp - baza_dvp) / baza_dvp if baza_dvp > 0 else 0
    korekta_dvp = max(0.94, min(1.06, 1.0 + (roznica_w_procentach * 0.10)))
    
    korekta_strefy = 1.0
    strefa_txt = ""
    
    if stat_key == '3PM' or (stat_key == 'PTS' and pozycja == 'G'):
        korekta_strefy = max(0.92, min(1.08, opp_3pm_allowed / L_AVG_3PM))
        strefa_txt = f" | 🎯 Obrona 3PT: Tracą {round(opp_3pm_allowed, 1)} trójek"
    elif stat_key == 'REB' or (stat_key == 'PTS' and pozycja in ['C', 'F']):
        korekta_strefy = max(0.92, min(1.08, opp_reb_allowed / L_AVG_REB))
        strefa_txt = f" | 🧱 Pomalowane: Tracą {round(opp_reb_allowed, 1)} zbiórek"
    
    projekcja_finalna = max(0.0, proj_baza * korekta_dvp * korekta_strefy * korekta_kontuzji * fatigue_multi * blowout_multi)
    
    y_train = y[-15:]
    std_dev = math.sqrt(sum((x - (sum(y_train) / len(y_train))) ** 2 for x in y_train) / (len(y_train) - 1)) if len(y_train) > 1 else 2.0
    if std_dev < 1.0: std_dev = 1.5
    
    h2h_avg = round(sum(h2h_stats) / len(h2h_stats), 1) if h2h_stats else 0
    h2h_history_list = ", ".join(map(str, reversed(h2h_stats))) if h2h_stats else "Brak"
    
    implied_total = 0.0
    if game_total > 0:
        if team_spread < 0: implied_total = (game_total / 2) + (abs(team_spread) / 2)
        else: implied_total = (game_total / 2) - (abs(team_spread) / 2)
    
    split_avg = round(sum(split_stats)/len(split_stats), 1) if split_stats else 0.0
    
    uwagi_txt = f"USG: {avg_usg}% | Tempo: {avg_pace}{strefa_txt}"
    if is_leader: uwagi_txt += " | 🔥 Playoff Mins"
    if is_b2b: uwagi_txt += " | 😴 ZMĘCZENIE (B2B)"
    if is_blowout: uwagi_txt += f" | 🚨 BLOWOUT RISK"
    if absencje_wplywajace:
        boost_pct = round((korekta_kontuzji - 1.0) * 100)
        znak = "+" if boost_pct > 0 else ""
        uwagi_txt += f" | ⚠️ ON/OFF {znak}{boost_pct}% (Brak: {absencje_wplywajace[0]}){on_off_text}"
    
    if implied_total > 0: uwagi_txt += f" | 🎰 Przewidywane Pkt Drużyny: {round(implied_total, 1)}"
    if split_avg > 0:
        uwagi_txt += f" | 🏠 Śr. Dom: {split_avg}" if is_home_game else f" | ✈️ Śr. Wyjazd: {split_avg}"
    
    return {
        "projekcja": round(projekcja_finalna, 1),
        "std_dev": std_dev,
        "history": l10_stats,
        "all_stats": wszystkie_statystyki,
        "dvp": dvp,
        "uwagi_txt": uwagi_txt,
        "h2h_avg": h2h_avg,
        "h2h_history": h2h_history_list,
        "ranga": "Lider" if is_leader else "Zmiennik"
    }, "OK"

# ==========================================
# 📊 MODUŁ STATYSTYK DRUŻYNOWYCH (SMART CACHE)
# ==========================================
def generuj_pelny_raport_druzynowy_nba():
    plik_raportu = 'nba_teams.json'
    plik_cache = 'nba_season_cache.json'
    
    # 🛑 BEZPIECZNIK: Wykonaj tylko raz dziennie
    if os.path.exists(plik_raportu):
        mod_time = datetime.fromtimestamp(os.path.getmtime(plik_raportu))
        if mod_time.strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d'):
            return 

    print("\n📊 Generowanie ZAAWANSOWANEGO raportu NBA (Statystyki z całego sezonu)...")
    inicjalizuj_druzyny()
    
    try:
        with open(plik_cache, 'r', encoding='utf-8') as f: cache_meczow = json.load(f)
    except:
        cache_meczow = {}

    try:
        time.sleep(0.15)
        res = requests.get(f"https://v2.nba.api-sports.io/games?season={SEZON_NBA}", headers=HEADERS_SPORTS).json()
        wszystkie_mecze = [m for m in res.get('response', []) if m['status']['long'] == 'Finished']
    except Exception as e:
        print(f"❌ Błąd pobierania terminarza: {e}")
        return

    brakujace_id = [str(m['id']) for m in wszystkie_mecze if str(m['id']) not in cache_meczow]

    if brakujace_id:
        print(f"🔄 Pobieram szczegóły dla {len(brakujace_id)} nowych meczów (Smart Cache)...")
        for i, g_id in enumerate(brakujace_id):
            if i > 0 and i % 50 == 0: print(f"  -> Pobrano {i} z {len(brakujace_id)}...")
            
            dane = pobierz_surowe_staty_meczu(g_id)
            if not dane: continue
            
            teams_stats = {}
            for z in dane:
                t_id = str(z['team']['id'])
                if t_id not in teams_stats:
                    teams_stats[t_id] = {'pts': 0, 'reb': 0, 'ast': 0, '3pm': 0, '3pa': 0, 'fta': 0, 'fouls': 0, 'fga': 0, 'tov': 0, 'min': 0.0}

                minuty = parse_min(z.get('min', '0'))
                if minuty > 0:
                    teams_stats[t_id]['min'] += minuty
                    teams_stats[t_id]['pts'] += z.get('points', 0) or 0
                    teams_stats[t_id]['reb'] += z.get('totReb', 0) or 0
                    teams_stats[t_id]['ast'] += z.get('assists', 0) or 0
                    teams_stats[t_id]['3pm'] += z.get('tpm', 0) or 0
                    teams_stats[t_id]['3pa'] += z.get('tpa', 0) or 0
                    teams_stats[t_id]['fta'] += z.get('fta', 0) or 0
                    teams_stats[t_id]['fga'] += z.get('fga', 0) or 0
                    teams_stats[t_id]['tov'] += z.get('turnovers', 0) or 0
                    teams_stats[t_id]['fouls'] += (z.get('pfouls', 0) or z.get('fouls', 0) or 0)

            if len(teams_stats) == 2:
                cache_meczow[g_id] = teams_stats

        with open(plik_cache, 'w', encoding='utf-8') as f:
            json.dump(cache_meczow, f)

    # 🧮 AGREGACJA WYNIKÓW
    druzyny_sumy = {str(tid): {'games':0, 'pts':0, 'reb':0, 'ast':0, '3pm':0, '3pa':0, 'fta':0, 'pace':0,
                               'opp_pts':0, 'opp_reb':0, 'opp_ast':0, 'opp_3pm':0, 'opp_3pa':0, 'opp_fta':0, 'opp_fouls':0}
                    for tid in NBA_TEAMS.values()}

    for g_id, data in cache_meczow.items():
        t_keys = list(data.keys())
        if len(t_keys) != 2: continue
        t1, t2 = t_keys[0], t_keys[1]

        for team_id, opp_id in [(t1, t2), (t2, t1)]:
            if team_id in druzyny_sumy and opp_id in data:
                druzyny_sumy[team_id]['games'] += 1
                druzyny_sumy[team_id]['pts'] += data[team_id]['pts']
                druzyny_sumy[team_id]['reb'] += data[team_id]['reb']
                druzyny_sumy[team_id]['ast'] += data[team_id]['ast']
                druzyny_sumy[team_id]['3pm'] += data[team_id]['3pm']
                druzyny_sumy[team_id]['3pa'] += data[team_id]['3pa']
                druzyny_sumy[team_id]['fta'] += data[team_id]['fta']
                druzyny_sumy[team_id]['pace'] += data[team_id]['fga'] + (0.44 * data[team_id]['fta']) + data[team_id]['tov']

                druzyny_sumy[team_id]['opp_pts'] += data[opp_id]['pts']
                druzyny_sumy[team_id]['opp_reb'] += data[opp_id]['reb']
                druzyny_sumy[team_id]['opp_ast'] += data[opp_id]['ast']
                druzyny_sumy[team_id]['opp_3pm'] += data[opp_id]['3pm']
                druzyny_sumy[team_id]['opp_3pa'] += data[opp_id]['3pa']
                druzyny_sumy[team_id]['opp_fta'] += data[opp_id]['fta']
                druzyny_sumy[team_id]['opp_fouls'] += data[opp_id]['fouls']

    raport_finalny = []
    for nazwa, tid in NBA_TEAMS.items():
        s = druzyny_sumy.get(str(tid))
        if not s or s['games'] == 0: continue
        g = s['games']
        raport_finalny.append({
            "Zespol": nazwa,
            "Mecze": g,
            "Pace": round(s['pace']/g, 1),
            "Zdobyte_PTS": round(s['pts']/g, 1),
            "Zdobyte_REB": round(s['reb']/g, 1),
            "Zdobyte_AST": round(s['ast']/g, 1),
            "Zdobyte_3PM": round(s['3pm']/g, 1),
            "Zdobyte_FTA": round(s['fta']/g, 1),
            "Tracone_PTS": round(s['opp_pts']/g, 1),
            "Tracone_REB": round(s['opp_reb']/g, 1),
            "Tracone_AST": round(s['opp_ast']/g, 1),
            "Tracone_3PM": round(s['opp_3pm']/g, 1),
            "Tracone_3PA": round(s['opp_3pa']/g, 1),
            "Tracone_FTA": round(s['opp_fta']/g, 1),
            "Wymuszone_Faule": round(s['opp_fouls']/g, 1)
        })

    if raport_finalny:
        raport_finalny = sorted(raport_finalny, key=lambda x: x['Zespol'])
        with open(plik_raportu, 'w', encoding='utf-8') as f:
            json.dump(raport_finalny, f, ensure_ascii=False, indent=4)
        print("✅ Zapisano kompletne statystyki drużynowe NBA (Cały Sezon)!")
        wyslij_plik_na_githuba(plik_raportu, "Aktualizacja statystyk drużynowych NBA")

# ==========================================
# GŁÓWNA PĘTLA
# ==========================================
def uruchom_system_pro():
    inicjalizuj_druzyny()
    rozlicz_wczorajsze_typy()
    pobierz_dzisiejsze_kontuzje() 
    generuj_pelny_raport_druzynowy_nba() # 🚀 GENERATOR STATYSTYK DRUŻYNOWYCH
    
    try:
        with open(SMART_MONEY_FILE, 'r') as f: 
            smart_money_db = json.load(f)
            if not isinstance(smart_money_db, dict): smart_money_db = {}
    except: smart_money_db = {}
    
    try:
        with open(ODDS_CACHE_FILE, 'r') as f: 
            odds_cache = json.load(f)
            if not isinstance(odds_cache, dict): odds_cache = {}
    except: odds_cache = {}
    
    data_dzis = datetime.now().strftime('%Y-%m-%d')
    print(f"\n📡 Pobieram listę meczów NBA na dzień: {data_dzis}...\n")
    
    try: 
        res_events = requests.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={ODDS_API_KEY}')
        events = res_events.json()
        if isinstance(events, dict) and 'message' in events:
            print(f"❌ BŁĄD THE ODDS API (Mecze): {events['message']}")
            return []
    except: return []

    mecze_dzis = [e for e in events if (datetime.strptime(e['commence_time'], '%Y-%m-%dT%H:%M:%SZ') - timedelta(hours=5)).strftime('%Y-%m-%d') == data_dzis]
    wyniki = []

    for i, ev in enumerate(mecze_dzis, 1):
        m_str = f"{ev['away_team']} @ {ev['home_team']}"
        home_team, away_team = ev['home_team'], ev['away_team']
        print(f"[{i}/{len(mecze_dzis)}] Tafla: {m_str}")
        
        cache_key = str(ev['id'])
        obecny_czas = time.time()
        
        if cache_key in odds_cache and (obecny_czas - odds_cache[cache_key]['timestamp']) < ODDS_CACHE_EXPIRY:
            odds = odds_cache[cache_key]['data']
        else:
            try: 
                res_odds = requests.get(f'https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev["id"]}/odds?apiKey={ODDS_API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal')
                odds = res_odds.json()
            except Exception as e: 
                print(f"  ❌ BŁĄD POŁĄCZENIA: {e}")
                continue
            
            if 'bookmakers' not in odds or len(odds['bookmakers']) == 0: 
                continue
                
            odds_cache[cache_key] = {'timestamp': obecny_czas, 'data': odds}
            with open(ODDS_CACHE_FILE, 'w') as f: json.dump(odds_cache, f)
        
        game_spreads = {}
        game_total = 0.0
        for bm in odds.get('bookmakers', []):
            for mkt in bm.get('markets', []):
                if mkt['key'] == 'spreads':
                    for oc in mkt['outcomes']: game_spreads[oc['name']] = oc.get('point', 0.0)
                elif mkt['key'] == 'totals':
                    for oc in mkt['outcomes']:
                        if oc['name'] == 'Over': game_total = float(oc.get('point', 0.0))
        
        przetworzone = set()
        for bm in odds['bookmakers']:
            for mkt in bm['markets']:
                
                s_key, s_pl = (
                    ('PTS', 'Punkty (PTS)') if mkt['key'] == 'player_points' else 
                    ('REB', 'Zbiórki (REB)') if mkt['key'] == 'player_rebounds' else 
                    ('AST', 'Asysty (AST)') if mkt['key'] == 'player_assists' else 
                    ('3PM', 'Rzuty za 3 (3PM)') if mkt['key'] == 'player_threes' else 
                    ('PRA', 'Pkt+Zb+As (PRA)') if mkt['key'] == 'player_points_rebounds_assists' else (None, None)
                )
                if not s_key: continue
                
                for oc in mkt['outcomes']:
                    p_name, linia, kurs = oc['description'], oc['point'], oc['price']
                    
                    if oc['name'] == 'Over' and f"{p_name}_{s_key}" not in przetworzone:
                        przetworzone.add(f"{p_name}_{s_key}")
                        print(f"  -> Skanuję: {p_name:<20} ({s_key}) ", end="", flush=True)
                        
                        sm_key = f"{ev['id']}_{p_name}_{s_key}"
                        is_smart_money = False
                        sm_text = ""
                        
                        if sm_key not in smart_money_db:
                            smart_money_db[sm_key] = {"line": linia, "price": kurs}
                        else:
                            old_line = smart_money_db[sm_key]["line"]
                            old_price = smart_money_db[sm_key]["price"]
                            if linia > old_line:
                                is_smart_money = True
                                sm_text = f" | 💰 SMART MONEY (Linia skoczyła z {old_line} na {linia})"
                            elif linia == old_line and kurs <= old_price - 0.15:
                                is_smart_money = True
                                sm_text = f" | 💰 SMART MONEY (Spadek kursu na {kurs})"
                        
                        p_id, pos = pobierz_id_i_pozycje(p_name, home_team)
                        is_home, opp_team, team_id = True, away_team, NBA_TEAMS.get(home_team)
                        team_spread = game_spreads.get(home_team, 0.0)
                        
                        if not p_id:
                            p_id, pos = pobierz_id_i_pozycje(p_name, away_team)
                            is_home, opp_team, team_id = False, home_team, NBA_TEAMS.get(away_team)
                            team_spread = game_spreads.get(away_team, 0.0)
                        
                        opp_id = NBA_TEAMS.get(opp_team)
                        
                        if p_id and opp_id and team_id:
                            s_data = przeanalizuj_gracza_ml(p_id, p_name, pos, s_key, team_id, opp_id, linia, data_dzis, team_spread, game_total, is_home)
                            if s_data and s_data[0] is not None:
                                s = s_data[0]
                                print(f"✅ [Proj: {s['projekcja']} | DvP: {s['dvp']}]")
                                proj = s['projekcja']
                                typ = "OVER" if proj > linia else "UNDER"
                                z_score = (linia - proj) / s['std_dev'] 
                                prob_under = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
                                true_prob = (1.0 - prob_under) if typ == "OVER" else prob_under
                                ev_val = (true_prob * kurs) - 1

                                if true_prob <= 0.55: continue

                                all_s = s['all_stats']
                                if typ == "OVER":
                                    pokrycie_l5 = int((sum(1 for x in all_s[-5:] if x > linia) / 5) * 100) if len(all_s) >= 5 else 0
                                    pokrycie_l10 = int((sum(1 for x in all_s[-10:] if x > linia) / 10) * 100) if len(all_s) >= 10 else 0
                                    pokrycie_sezon = int((sum(1 for x in all_s if x > linia) / len(all_s)) * 100) if all_s else 0
                                    m_color = "rank-green" if s['dvp'] > linia else "rank-red"
                                else:
                                    pokrycie_l5 = int((sum(1 for x in all_s[-5:] if x < linia) / 5) * 100) if len(all_s) >= 5 else 0
                                    pokrycie_l10 = int((sum(1 for x in all_s[-10:] if x < linia) / 10) * 100) if len(all_s) >= 10 else 0
                                    pokrycie_sezon = int((sum(1 for x in all_s if x < linia) / len(all_s)) * 100) if all_s else 0
                                    m_color = "rank-green" if s['dvp'] < linia else "rank-red"
                                
                                ostateczne_uwagi = s['uwagi_txt'] + sm_text
                                
                                is_value_bet = ev_val >= 0.04
                                is_safe_bet = true_prob >= 0.75 and pokrycie_l5 >= 80
                                
                                is_stable_bet = False
                                if s['history']:
                                    mean = sum(s['history']) / len(s['history'])
                                    if mean > 0:
                                        cv = s['std_dev'] / mean
                                        if typ == "OVER":
                                            if cv < 0.30 and mean >= (linia * 0.75) and m_color == 'rank-green':
                                                is_stable_bet = True
                                        else:
                                            if cv < 0.30 and mean <= (linia * 1.25) and m_color == 'rank-green':
                                                is_stable_bet = True
                                
                                is_graal_bet = is_value_bet and is_safe_bet and is_stable_bet
                                
                                wyniki.append({
                                    "zawodnik": p_name, "mecz": m_str, "data": data_dzis,
                                    "rynek": s_pl, "linia": linia, "projekcja": proj, 
                                    "roznica": round(abs(proj - linia), 2), "kurs": kurs, "typ": typ, 
                                    "ev": round(ev_val, 3), "true_prob": true_prob,
                                    "uwagi": ostateczne_uwagi, 
                                    "l5": f"{pokrycie_l5}%", "l10": f"{pokrycie_l10}%", "sezon": f"{pokrycie_sezon}%", 
                                    "lokacja": "DOM" if is_home else "WYJ",
                                    "matchup_rank": f"Obrona pozwala na: {s['dvp']} (vs {s['ranga']} {pos})", 
                                    "matchup_color": m_color, 
                                    "history": s['history'], "opp_name": opp_team, 
                                    "h2h_avg": s['h2h_avg'], "h2h_history": s['h2h_history'], "smart_money": is_smart_money,
                                    "is_value": is_value_bet,
                                    "is_safe": is_safe_bet,
                                    "is_stable": is_stable_bet,
                                    "is_graal": is_graal_bet
                                })
                            else: 
                                msg = s_data[1] if s_data else "Błąd nieznany"
                                print(f"❌ ({msg})")
                        else: print(f"❌ (Nie znaleziono w Rosterze)")

    with open(SMART_MONEY_FILE, 'w') as f: json.dump(smart_money_db, f)

    for i, w1 in enumerate(wyniki):
        if w1['ev'] > 0.02 and w1['typ'] == 'OVER' and 'Asysty' in w1['rynek']:
            naj_strzelec = None
            naj_ev = 0
            for j, w2 in enumerate(wyniki):
                if i != j and w2['mecz'] == w1['mecz'] and w2['lokacja'] == w1['lokacja']:
                    if w2['typ'] == 'OVER' and ('Punkty' in w2['rynek'] or 'Rzuty za 3' in w2['rynek']):
                        if w2['ev'] > naj_ev:
                            naj_ev = w2['ev']
                            naj_strzelec = w2
            
            if naj_strzelec and naj_strzelec['ev'] > 0.02:
                txt1 = f" | 🔗 ZŁOTA PARA SGP: Łącz z OVER {naj_strzelec['zawodnik']} ({naj_strzelec['rynek']})"
                txt2 = f" | 🔗 ZŁOTA PARA SGP: Asystuje {w1['zawodnik']} (OVER Asyst)"
                if "ZŁOTA PARA" not in w1['uwagi']: w1['uwagi'] += txt1
                if "ZŁOTA PARA" not in naj_strzelec['uwagi']: naj_strzelec['uwagi'] += txt2

    return wyniki

if __name__ == "__main__":
    print("==================================================")
    print("🚀 START: QUANT AI BOTS (NBA PRO v14.1 PLAYOFF EDITION + TEAM STATS)")
    print("==================================================")
    
    start = time.time()
    final_data = uruchom_system_pro()
    
    if final_data:
        final_data = sorted(final_data, key=lambda x: x['ev'], reverse=True)
        with open('nba.json', 'w', encoding='utf-8') as f: json.dump(final_data, f, ensure_ascii=False, indent=4)
        print("\n💾 SUKCES: Zapisano plik 'nba.json' na Twoim dysku!")
        
        wyslij_plik_na_githuba('nba.json', "Update NBA (v14.1 Playoff Edition)")
        print("🌐 Wysłano aktualizację JSON na stronę GitHuba!")
        
        top = [t for t in final_data if t['ev'] > 0.05 and t['true_prob'] > 0.55][:5]
        
        if top:
            msg = "🚨 <b>RAPORT QUANT AI: NBA (PRO ULTIMATE)</b> 🚨\n\n"
            for t in top: 
                msg += f"🏀 {t['zawodnik']} - {t['rynek']}\n"
                msg += f"👉 <b>{t['typ']} {t['linia']}</b> @ {t['kurs']} (EV: +{round(t['ev'] * 100, 1)}%)\n"
                msg += f"🤖 ML: {t['projekcja']} | {t['uwagi']}\n"
                msg += f"📈 L10: {list(reversed(t['history']))} | {t['matchup_rank']}\n\n"
            wyslij_powiadomienie_telegram(msg)
            print("📲 Wysłano raport na Telegram!")
            
    print(f"\n✅ Zakończono! Czas wykonania: {round((time.time() - start)/60, 2)} minut.")
