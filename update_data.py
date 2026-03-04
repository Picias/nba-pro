import requests
import json
import time
import math
import statistics
from datetime import datetime, timedelta
from nba_api.stats.static import players
from nba_api.stats.endpoints import playergamelog, leaguedashteamstats

# ==========================================
# KONFIGURACJA API I SKRYPTU
# ==========================================
API_KEY = '4c71d3544ec6da13869684942dd34340'
SPORT = 'basketball_nba'
REGIONS = 'us'
MARKETS = 'player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists,spreads'

DNI_DO_PRZODU = 0 

# ==========================================
# KAMUFLAŻ DLA SERWERÓW PYTHONANYWHERE (Obejście Cloudflare)
# ==========================================
NBA_HEADERS = {
    'Host': 'stats.nba.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

NBA_TEAMS = {
    'ATL': 'Atlanta Hawks', 'BOS': 'Boston Celtics', 'BKN': 'Brooklyn Nets',
    'CHA': 'Charlotte Hornets', 'CHI': 'Chicago Bulls', 'CLE': 'Cleveland Cavaliers',
    'DAL': 'Dallas Mavericks', 'DEN': 'Denver Nuggets', 'DET': 'Detroit Pistons',
    'GSW': 'Golden State Warriors', 'HOU': 'Houston Rockets', 'IND': 'Indiana Pacers',
    'LAC': 'Los Angeles Clippers', 'LAL': 'Los Angeles Lakers', 'MEM': 'Memphis Grizzlies',
    'MIA': 'Miami Heat', 'MIL': 'Milwaukee Bucks', 'MIN': 'Minnesota Timberwolves',
    'NOP': 'New Orleans Pelicans', 'NYK': 'New York Knicks', 'OKC': 'Oklahoma City Thunder',
    'ORL': 'Orlando Magic', 'PHI': 'Philadelphia 76ers', 'PHX': 'Phoenix Suns',
    'POR': 'Portland Trail Blazers', 'SAC': 'Sacramento Kings', 'SAS': 'San Antonio Spurs',
    'TOR': 'Toronto Raptors', 'UTA': 'Utah Jazz', 'WAS': 'Washington Wizards'
}

MONTHS = {'JAN':1, 'FEB':2, 'MAR':3, 'APR':4, 'MAY':5, 'JUN':6, 'JUL':7, 'AUG':8, 'SEP':9, 'OCT':10, 'NOV':11, 'DEC':12}

def parse_minutes(min_str):
    if isinstance(min_str, str) and ':' in min_str:
        m, s = min_str.split(':')
        return int(m) + int(s) / 60.0
    elif isinstance(min_str, (int, float)):
        return float(min_str)
    return 0.0

def tlumacz_rynek_na_nba(market_name):
    if market_name == 'player_points': return 'PTS', 'Punkty (PTS)'
    if market_name == 'player_rebounds': return 'REB', 'Zbiórki (REB)'
    if market_name == 'player_assists': return 'AST', 'Asysty (AST)'
    if market_name == 'player_threes': return 'FG3M', 'Trójki (3PTM)'
    if market_name == 'player_points_rebounds_assists': return 'PRA', 'PTS+REB+AST'
    return None, None

def pobierz_defensywe_ligowa():
    print("Pobieranie statystyk defensywnych oraz tempa (PACE) z bazy NBA...")
    for proba in range(3):
        try:
            stats_def = leaguedashteamstats.LeagueDashTeamStats(
                measure_type_detailed_defense='Opponent', per_mode_detailed='PerGame', timeout=60, headers=NBA_HEADERS
            ).get_normalized_dict()['LeagueDashTeamStats']

            stats_adv = leaguedashteamstats.LeagueDashTeamStats(
                measure_type_detailed_defense='Advanced', per_mode_detailed='PerGame', timeout=60, headers=NBA_HEADERS
            ).get_normalized_dict()['LeagueDashTeamStats']
            
            print("✅ Modele obrony i tempa wczytane pomyślnie!")
            break
        except Exception as e:
            print(f"  [!] Serwer NBA zwalnia (Próba {proba+1}/3)...")
            time.sleep(3)
            if proba == 2: 
                print("❌ Błąd krytyczny pobierania obrony. Używam danych domyślnych.")
                return {} 

    avg_pts = sum(t['OPP_PTS'] for t in stats_def) / len(stats_def)
    avg_reb = sum(t['OPP_REB'] for t in stats_def) / len(stats_def)
    avg_ast = sum(t['OPP_AST'] for t in stats_def) / len(stats_def)
    avg_fg3m = sum(t['OPP_FG3M'] for t in stats_def) / len(stats_def)
    avg_pace = sum(t['PACE'] for t in stats_adv) / len(stats_adv)
    
    pace_map = {t['TEAM_NAME'].replace("LA Clippers", "Los Angeles Clippers"): t['PACE'] / avg_pace for t in stats_adv}

    druzyny_def = {}
    for t in stats_def:
        team_name = t['TEAM_NAME'].replace("LA Clippers", "Los Angeles Clippers")
        druzyny_def[team_name] = {
            'PTS_rank': t['OPP_PTS_RANK'], 'PTS_mult': t['OPP_PTS'] / avg_pts,
            'REB_rank': t['OPP_REB_RANK'], 'REB_mult': t['OPP_REB'] / avg_reb,
            'AST_rank': t['OPP_AST_RANK'], 'AST_mult': t['OPP_AST'] / avg_ast,
            'FG3M_rank': t['OPP_FG3M_RANK'], 'FG3M_mult': t['OPP_FG3M'] / avg_fg3m,
            'PRA_rank': t['OPP_PTS_RANK'], 
            'PRA_mult': (t['OPP_PTS']+t['OPP_REB']+t['OPP_AST']) / (avg_pts+avg_reb+avg_ast),
            'PACE_mult': pace_map.get(team_name, 1.0) 
        }
    return druzyny_def

def pobierz_prawdziwe_statystyki_nba(nazwa_gracza, linia, stat_key, mecz_string, druzyny_def, data_docelowa_str):
    try:
        znalezieni = players.find_players_by_full_name(nazwa_gracza)
        if not znalezieni: return None, "Brak w bazie"
        
        player_id = znalezieni[0]['id']
        time.sleep(1.5) # Zwiększona pauza anty-botowa
        
        mecze = None
        blad = ""
        for proba in range(3):
            try:
                logi = playergamelog.PlayerGameLog(player_id=player_id, timeout=60, headers=NBA_HEADERS)
                mecze = logi.get_normalized_dict()['PlayerGameLog']
                break
            except Exception as e:
                blad = str(e)
                time.sleep(2)
                
        if not mecze: return None, f"Timeout: {blad[:30]}..."
            
        skrot_druzyny_gracza = mecze[0]['MATCHUP'][:3] 
        pelna_nazwa_druzyny = NBA_TEAMS.get(skrot_druzyny_gracza, "")
        gosc, gospodarz = mecz_string.split(' @ ')
        przeciwnik = gospodarz if pelna_nazwa_druzyny == gosc else gosc
        czy_dzis_w_domu = (pelna_nazwa_druzyny == gospodarz)
        
        is_b2b = False
        data_docelowa_dt = datetime.strptime(data_docelowa_str, '%Y-%m-%d')
        parts = mecze[0]['GAME_DATE'].replace(',', '').split()
        if len(parts) == 3:
            m = MONTHS.get(parts[0].upper(), 1)
            ostatni_mecz_dt = datetime(int(parts[2]), m, int(parts[1]))
            if (data_docelowa_dt - ostatni_mecz_dt).days == 1:
                is_b2b = True

        wartosci, minuty_lista, wartosci_lokacja = [], [], []
        
        for mecz in mecze:
            if stat_key == 'PRA': wartosc = mecz['PTS'] + mecz['REB'] + mecz['AST']
            else: wartosc = mecz.get(stat_key, 0)
            
            wartosci.append(wartosc)
            minuty_lista.append(parse_minutes(mecz.get('MIN', 0)))
            
            mecz_byl_w_domu = " vs. " in mecz['MATCHUP']
            if mecz_byl_w_domu == czy_dzis_w_domu:
                wartosci_lokacja.append(wartosc)
        
        if not wartosci or sum(minuty_lista) == 0: return None, "Brak minut"

        l5_stats = wartosci[:5]
        l10_stats = wartosci[:10]
        l5_mins = minuty_lista[:5]
        
        historia_wykres = list(reversed(l10_stats))

        try:
            std_dev = statistics.stdev(wartosci) if len(wartosci) > 1 else 1.0
        except:
            std_dev = 1.0
        if std_dev == 0: std_dev = 0.5 

        pokrycie_l5 = sum(1 for p in l5_stats if p > linia)
        pokrycie_l10 = sum(1 for p in l10_stats if p > linia)
        pokrycie_sezon = sum(1 for p in wartosci if p > linia)
        
        pokrycie_lokacja = sum(1 for p in wartosci_lokacja if p > linia)
        ilosc_lokacja = len(wartosci_lokacja)
        lokacja_proc_str = f"{int((pokrycie_lokacja/ilosc_lokacja)*100)}% ({pokrycie_lokacja}/{ilosc_lokacja})" if ilosc_lokacja > 0 else "-"
        prefix_lokacji = "DOM" if czy_dzis_w_domu else "WYJ"
        lokacja_pelny_str = f"{prefix_lokacji}: {lokacja_proc_str}"
        
        ppm_l5 = sum(l5_stats) / sum(l5_mins) if sum(l5_mins) > 0 else 0
        ppm_sezon = sum(wartosci) / sum(minuty_lista) if sum(minuty_lista) > 0 else 0
        przewidywane_minuty = sum(l5_mins) / len(l5_mins) if l5_mins else 0
        
        wazona_ppm = (ppm_l5 * 0.6) + (ppm_sezon * 0.4)
        bazowa_projekcja = wazona_ppm * przewidywane_minuty
        
        mnoznik_def, mnoznik_pace, rank_obrony = 1.0, 1.0, 15
        if przeciwnik in druzyny_def:
            klucz_multi = f"{stat_key}_mult" if stat_key != 'PRA' else 'PRA_mult'
            klucz_rank = f"{stat_key}_rank" if stat_key != 'PRA' else 'PRA_rank'
            mnoznik_def = druzyny_def[przeciwnik].get(klucz_multi, 1.0)
            mnoznik_pace = druzyny_def[przeciwnik].get('PACE_mult', 1.0)
            rank_obrony = druzyny_def[przeciwnik].get(klucz_rank, 15)

        finalna_projekcja = bazowa_projekcja * mnoznik_def * mnoznik_pace * (0.93 if is_b2b else 1.0)
        
        return {
            "projekcja": round(finalna_projekcja, 1),
            "std_dev": std_dev, 
            "matchup_rank": rank_obrony,
            "l5_str": f"{int((pokrycie_l5/len(l5_stats))*100)}% ({pokrycie_l5}/{len(l5_stats)})",
            "l10_str": f"{int((pokrycie_l10/len(l10_stats))*100)}% ({pokrycie_l10}/{len(l10_stats)})" if l10_stats else "-",
            "sezon_str": f"{int((pokrycie_sezon/len(wartosci))*100)}%",
            "lokacja_str": lokacja_pelny_str,
            "is_b2b": is_b2b,
            "history": historia_wykres 
        }, "OK"
    except Exception as e:
        return None, f"Błąd wewnętrzny: {str(e)[:40]}"

def formatuj_pozycje(rank):
    if 11 <= rank % 100 <= 13: return f"{rank}th"
    if rank % 10 == 1: return f"{rank}st"
    if rank % 10 == 2: return f"{rank}nd"
    if rank % 10 == 3: return f"{rank}rd"
    return f"{rank}th"

def pobierz_mecze_i_kursy():
    data_docelowa = (datetime.now() + timedelta(days=DNI_DO_PRZODU)).strftime('%Y-%m-%d')
    print(f"Filtrowanie: Pobieram mecze WYŁĄCZNIE z datą {data_docelowa} (wg czasu w USA)\n")

    defensywa = pobierz_defensywe_ligowa()
    
    print("Łączenie z The Odds API w poszukiwaniu dostępnych meczów...")
    events_url = f'https://api.the-odds-api.com/v4/sports/{SPORT}/events?apiKey={API_KEY}'
    events = requests.get(events_url).json()
    
    mecze_do_analizy = []
    for event in events:
        utc_time = datetime.strptime(event['commence_time'], '%Y-%m-%dT%H:%M:%SZ')
        us_time = utc_time - timedelta(hours=5)
        data_meczu = us_time.strftime('%Y-%m-%d')
        if data_meczu == data_docelowa:
            mecze_do_analizy.append((event, data_meczu))

    calkowita_liczba_meczow = len(mecze_do_analizy)
    gotowe_typy = []

    if calkowita_liczba_meczow == 0:
        print(f"Nie znaleziono meczów na The Odds API dla tej daty.")
        return []
        
    print(f"Znaleziono {calkowita_liczba_meczow} mecz(ów) do analizy.\n")

    for i, (event, data_meczu) in enumerate(mecze_do_analizy, 1):
        event_id = event['id']
        matchup = f"{event['away_team']} @ {event['home_team']}"
        print(f"\n[{i}/{calkowita_liczba_meczow}] Mecz: {matchup} ({data_meczu})")

        odds_url = f'https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds?apiKey={API_KEY}&regions={REGIONS}&markets={MARKETS}&oddsFormat=decimal'
        odds_response = requests.get(odds_url).json()

        if not odds_response or 'bookmakers' not in odds_response or len(odds_response['bookmakers']) == 0:
            print("  -> Brak dostępnych zakładów w systemie The Odds API.")
            continue
        
        blowout_risk = False
        spread_value = 0
        for bookmaker in odds_response['bookmakers']:
            for market in bookmaker.get('markets', []):
                if market['key'] == 'spreads' and market.get('outcomes'):
                    point = market['outcomes'][0].get('point', 0)
                    if abs(point) >= 11.5:
                        blowout_risk = True
                        spread_value = abs(point)
                    break 
            if blowout_risk: break

        znaleziono_typy_w_meczu = False
        przetworzone_linie = set() 

        for bookmaker in odds_response['bookmakers']:
            for market in bookmaker.get('markets', []):
                market_key = market['key']
                nba_stat_key, nazwa_rynku_pl = tlumacz_rynek_na_nba(market_key)
                if not nba_stat_key: continue

                for outcome in market.get('outcomes', []):
                    player_name = outcome.get('description', '')
                    typ = outcome.get('name')
                    linia = outcome.get('point', 0)
                    kurs = outcome.get('price', 1.90) 
                    
                    if typ == 'Over' and linia > 0:
                        unikalny_klucz = f"{player_name}_{market_key}"
                        if unikalny_klucz in przetworzone_linie: continue
                            
                        przetworzone_linie.add(unikalny_klucz)
                        znaleziono_typy_w_meczu = True
                        
                        print(f"  -> Analiza: {player_name} | {nazwa_rynku_pl} ({linia})...", end=" ", flush=True)
                        
                        staty, wiadomosc = pobierz_prawdziwe_statystyki_nba(player_name, linia, nba_stat_key, matchup, defensywa, data_docelowa)
                        
                        if staty:
                            print("✅")
                            projekcja = staty['projekcja']
                            std_dev = staty['std_dev']
                            zalecany_typ = "OVER" if projekcja > linia else "UNDER"
                            roznica = round(abs(projekcja - linia), 1)
                            rank_obr = staty['matchup_rank']
                            
                            z_score = (linia - projekcja) / std_dev 
                            prob_under = 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0)))
                            prob_over = 1.0 - prob_under
                            true_prob = prob_over if zalecany_typ == "OVER" else prob_under
                            
                            ev_val = (true_prob * kurs) - 1 
                            
                            uwagi = []
                            if staty.get('is_b2b'): uwagi.append("😴 B2B")
                            if blowout_risk: uwagi.append(f"⚠️ Blowout (±{spread_value})")
                            uwagi_str = " | ".join(uwagi) if uwagi else "-"

                            kolor_matchupu = "rank-red" if (rank_obr <= 14 and zalecany_typ == "OVER") or (rank_obr > 14 and zalecany_typ == "UNDER") else "rank-green"
                            
                            gotowe_typy.append({
                                "zawodnik": player_name,
                                "mecz": matchup,
                                "data": data_meczu,
                                "rynek": nazwa_rynku_pl,
                                "linia": linia,
                                "projekcja": projekcja,
                                "roznica": roznica,
                                "ev": round(ev_val, 3), 
                                "uwagi": uwagi_str,     
                                "typ": zalecany_typ,
                                "kurs": kurs,
                                "l5": staty['l5_str'],
                                "l10": staty['l10_str'],
                                "sezon": staty['sezon_str'],
                                "lokacja": staty['lokacja_str'],
                                "matchup_rank": formatuj_pozycje(rank_obr),
                                "matchup_color": kolor_matchupu,
                                "history": staty['history'] 
                            })
                        else:
                            print(f"❌ ({wiadomosc})")
                            
        if not znaleziono_typy_w_meczu:
            print("  -> Brak dostępnych zakładów w tym meczu.")

    return gotowe_typy

if __name__ == "__main__":
    start_time = time.time()
    dane_dla_html = pobierz_mecze_i_kursy()
    
    if dane_dla_html:
        with open('dane.json', 'w', encoding='utf-8') as f:
            json.dump(dane_dla_html, f, ensure_ascii=False, indent=4)
        
        minuty = int((time.time() - start_time) // 60)
        sekundy = int((time.time() - start_time) % 60)
        print(f"\n✅ ZAKOŃCZONO SUKCESEM!")
        print(f"Zapisano {len(dane_dla_html)} propozycji do pliku dane.json.")
        print(f"Czas analizy: {minuty} min {sekundy} sek.")
    else:
        print("\nZakończono. Brak danych do zapisania.")