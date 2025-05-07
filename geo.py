import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime
import itertools
import os
import time

st.set_page_config(page_title="Calcolatore Tragitto Multi-Tappa", layout="wide")

st.title("Calcolatore del Tragitto Minimo tra Casa e Lavori")

# Funzione per caricare il file CSV
def load_csv(uploaded_file):
    if uploaded_file is not None:
        try:
            # Prova prima con punto e virgola come separatore (formato italiano comune)
            df = pd.read_csv(uploaded_file, sep=";")
            # Controlla se abbiamo le colonne attese
            if not all(col in df.columns for col in ["CASA", "LAVORO", "GIORNO"]):
                # Prova con virgola come separatore
                df = pd.read_csv(uploaded_file, sep=",")
            
            # Pulisci gli spazi bianchi nelle intestazioni
            df.columns = df.columns.str.strip()
            return df
        except Exception as e:
            st.error(f"Errore nel caricamento del file: {e}")
            return None
    return None

# Funzione per geocodificare un indirizzo usando OpenStreetMap Nominatim API
def geocode_address(address):
    try:
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "TragittoCalculator/1.0"  # Necessario per le regole di Nominatim
        }
        
        response = requests.get(base_url, params=params, headers=headers)
        data = response.json()
        
        if data and len(data) > 0:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            return lat, lon, data[0]["display_name"] if "display_name" in data[0] else None
        else:
            return None, None, None
    except Exception as e:
        st.error(f"Errore durante la geocodifica: {e}")
        return None, None, None

# Funzione per ottenere suggerimenti di indirizzi
def get_address_suggestions(address):
    try:
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 3  # Ottieni più risultati per i suggerimenti
        }
        headers = {
            "User-Agent": "TragittoCalculator/1.0"
        }
        
        response = requests.get(base_url, params=params, headers=headers)
        data = response.json()
        
        suggestions = []
        if data and len(data) > 0:
            for item in data:
                if "display_name" in item:
                    suggestions.append(item["display_name"])
        return suggestions
    except Exception as e:
        return []

# Funzione per calcolare il percorso tra due punti usando OSRM
def get_route(start_coords, end_coords):
    try:
        base_url = "http://router.project-osrm.org/route/v1/driving/"
        url = f"{base_url}{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}"
        params = {
            "overview": "full",
            "geometries": "geojson"
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        if data["code"] == "Ok":
            route = data["routes"][0]
            distance = route["distance"] / 1000  # Converti in km
            duration = route["duration"] / 60  # Converti in minuti
            return distance, duration
        else:
            st.warning("Non è stato possibile calcolare il percorso")
            return None, None
    except Exception as e:
        st.error(f"Errore durante il calcolo del percorso: {e}")
        return None, None

# Funzione per calcolare la matrice delle distanze tra tutti i punti
def calculate_distance_matrix(coords_list):
    n = len(coords_list)
    distances = np.zeros((n, n))
    durations = np.zeros((n, n))
    
    for i in range(n):
        for j in range(n):
            if i != j:
                dist, dur = get_route(coords_list[i], coords_list[j])
                if dist is not None and dur is not None:
                    distances[i, j] = dist
                    durations[i, j] = dur
                else:
                    st.warning(f"Impossibile calcolare la distanza tra i punti {i} e {j}")
                    # Imposta valori predefiniti invece di fermare il calcolo
                    distances[i, j] = 9999  # Valore alto per evitare questo percorso
                    durations[i, j] = 9999
    
    return distances, durations

# Funzione per trovare il percorso ottimale (algoritmo greedy)
def find_optimal_route(distances, start_index):
    n = distances.shape[0]
    current = start_index
    path = [current]
    remaining = set(range(n))
    remaining.remove(current)
    
    # Se abbiamo solo casa e un lavoro
    if n <= 2:
        return list(range(n))
    
    # Percorso con casa -> lavori -> casa
    while remaining:
        if len(remaining) == 1 and 0 in remaining:
            # Se è rimasto solo casa (0), aggiungiamolo
            next_stop = 0
        else:
            # Trova il prossimo posto più vicino (non casa se ci sono ancora altri posti)
            next_stop = min(
                [i for i in remaining if (i != 0 or len(remaining) == 1)],
                key=lambda x: distances[current, x]
            )
        
        path.append(next_stop)
        remaining.remove(next_stop)
        current = next_stop
    
    # Se non torniamo a casa alla fine, aggiungiamo casa
    if path[-1] != 0:
        path.append(0)
    
    return path

# Funzione per verificare la validità di tutti gli indirizzi
def validate_addresses(addresses_list):
    invalid_addresses = []
    valid_addresses = []
    valid_coords = []
    
    for i, address in enumerate(addresses_list):
        lat, lon, full_address = geocode_address(address)
        if lat is None or lon is None:
            invalid_addresses.append((i, address, None))
        else:
            valid_addresses.append(address)
            valid_coords.append((lat, lon))
    
    return invalid_addresses, valid_addresses, valid_coords

# Funzione per calcolare e visualizzare la sommatoria dei km per tutti i giorni
def calculate_total_km_for_all_days(df):
    giorni_disponibili = df["GIORNO"].unique().tolist()
    risultati_totali = []
    distanza_totale_complessiva = 0
    durata_totale_complessiva = 0
    
    # Raccogliamo tutti gli indirizzi problematici
    problematic_addresses = []

    with st.spinner("Calcolo dei percorsi per tutti i giorni..."):
        for giorno in giorni_disponibili:
            # Filtra per il giorno corrente
            filtered_df = df[df["GIORNO"] == giorno]
            
            if not filtered_df.empty:
                # Ottieni tutti gli indirizzi unici per quel giorno
                casa_address = filtered_df["CASA"].iloc[0]
                lavoro_addresses = filtered_df["LAVORO"].unique().tolist()
                
                # Geocodifica tutti gli indirizzi
                coords_casa = geocode_address(casa_address)
                if coords_casa[0] is None:
                    problematic_addresses.append(("casa", casa_address, giorno))
                    continue
                
                coords_lavoro_list = []
                geocode_failed = False
                for addr in lavoro_addresses:
                    coords = geocode_address(addr)
                    if coords[0] is None:
                        problematic_addresses.append(("lavoro", addr, giorno))
                        geocode_failed = True
                    else:
                        coords_lavoro_list.append((coords[0], coords[1]))
                
                if geocode_failed:
                    continue
                
                # Crea lista completa di coordinate con casa come prima posizione
                all_coords = [(coords_casa[0], coords_casa[1])] + coords_lavoro_list
                
                # Calcola la matrice delle distanze
                distances, durations = calculate_distance_matrix(all_coords)
                
                if distances is None or durations is None:
                    st.warning(f"Impossibile calcolare la matrice delle distanze per il giorno {giorno}. Verrà saltato.")
                    continue
                
                # Trova il percorso ottimale
                optimal_route = find_optimal_route(distances, 0)
                
                # Calcola la distanza totale e la durata
                total_distance = 0
                total_duration = 0
                
                for i in range(len(optimal_route) - 1):
                    from_idx = optimal_route[i]
                    to_idx = optimal_route[i + 1]
                    total_distance += distances[from_idx, to_idx]
                    total_duration += durations[from_idx, to_idx]
                
                # Aggiungi ai totali complessivi
                distanza_totale_complessiva += total_distance
                durata_totale_complessiva += total_duration
                
                # Salva risultati per questo giorno
                risultati_totali.append({
                    "Giorno": giorno,
                    "Numero Lavori": len(lavoro_addresses),
                    "Distanza Totale (km)": round(total_distance, 2),
                    "Tempo Stimato (min)": round(total_duration, 0)
                })
    
    return risultati_totali, round(distanza_totale_complessiva, 2), round(durata_totale_complessiva, 0), problematic_addresses

# Sezione per il caricamento del file
uploaded_file = st.file_uploader("Carica il tuo file CSV", type=["csv"])

if uploaded_file:
    df = load_csv(uploaded_file)
    
    if df is not None:
        st.success("File caricato con successo!")
        
        # Mostra anteprima dei dati
        st.subheader("Anteprima dei dati")
        st.dataframe(df.head())
        
        # Aggiungi tab per separare le funzionalità
        tab1, tab2, tab3 = st.tabs(["Calcolo Giornaliero", "Riepilogo Totale", "Verifica Indirizzi"])
        
        with tab1:
            # Processo di aggiunta degli indirizzi se necessario
            if df.empty or (len(df) == 1 and df.iloc[0].isna().all()):
                st.info("Il file CSV è vuoto. Aggiungi i tuoi indirizzi.")
                
                with st.form("add_address_form"):
                    casa = st.text_input("Indirizzo di casa")
                    lavoro = st.text_input("Indirizzo di lavoro")
                    giorno = st.date_input("Giorno", datetime.now())
                    
                    submit = st.form_submit_button("Aggiungi")
                    
                    if submit and casa and lavoro:
                        new_row = pd.DataFrame({"CASA": [casa], "LAVORO": [lavoro], "GIORNO": [giorno.strftime("%d/%m/%Y")]})
                        df = pd.concat([df, new_row], ignore_index=True)
                        st.success("Indirizzo aggiunto!")
                        st.dataframe(df)
            
            # Sezione per selezionare un giorno dal CSV
            if not df.empty:
                giorni_disponibili = df["GIORNO"].unique().tolist()
                
                if giorni_disponibili:
                    giorno_selezionato = st.selectbox("Seleziona un giorno", giorni_disponibili)
                    
                    if st.button("Calcola Tragitto Ottimale"):
                        # Filtra per il giorno selezionato
                        filtered_df = df[df["GIORNO"] == giorno_selezionato]
                        
                        if not filtered_df.empty:
                            # Ottieni tutti gli indirizzi unici per quel giorno
                            casa_address = filtered_df["CASA"].iloc[0]  # Prendiamo il primo indirizzo casa come punto di partenza
                            lavoro_addresses = filtered_df["LAVORO"].unique().tolist()
                            
                            st.write(f"**Giorno selezionato:** {giorno_selezionato}")
                            st.write(f"**Indirizzo casa:** {casa_address}")
                            st.write(f"**Indirizzi lavoro ({len(lavoro_addresses)}):**")
                            for i, addr in enumerate(lavoro_addresses, 1):
                                st.write(f"{i}. {addr}")
                            
                            # Geocodifica tutti gli indirizzi
                            with st.spinner("Geocodifica degli indirizzi in corso..."):
                                # Raccogliere gli indirizzi problematici
                                problematic_addresses = []
                                
                                # Verifica indirizzo casa
                                lat_casa, lon_casa, full_casa = geocode_address(casa_address)
                                if lat_casa is None:
                                    problematic_addresses.append(("casa", casa_address))
                                
                                # Verifica indirizzi lavoro
                                for addr in lavoro_addresses:
                                    lat, lon, full_addr = geocode_address(addr)
                                    if lat is None:
                                        problematic_addresses.append(("lavoro", addr))
                            
                            # Se ci sono indirizzi problematici, mostra l'interfaccia di correzione
                            if problematic_addresses:
                                st.warning("Alcuni indirizzi non sono stati trovati. Per favore, correggi gli indirizzi seguenti:")
                                
                                # Crea un dizionario per memorizzare le correzioni
                                address_corrections = {}
                                for i, (addr_type, addr) in enumerate(problematic_addresses):
                                    st.subheader(f"Indirizzo {addr_type} non trovato: {addr}")
                                    
                                    # Ottieni suggerimenti
                                    suggestions = get_address_suggestions(addr)
                                    
                                    # Mostra i suggerimenti
                                    if suggestions:
                                        st.write("Suggerimenti:")
                                        for sugg in suggestions:
                                            if st.button(f"Usa: {sugg}", key=f"sugg_{i}_{sugg[:10]}"):
                                                # Imposta il suggerimento come correzione
                                                address_corrections[(addr_type, addr)] = sugg
                                    
                                    # Campo per inserire la correzione manuale
                                    corrected_addr = st.text_input(f"Correggi l'indirizzo {addr_type}", value=addr, key=f"corr_{i}")
                                    
                                    # Pulsante per verificare l'indirizzo
                                    col1, col2 = st.columns([1, 3])
                                    with col1:
                                        if st.button("Verifica", key=f"check_{i}"):
                                            lat, lon, full_addr = geocode_address(corrected_addr)
                                            if lat is not None:
                                                st.success(f"Indirizzo trovato: {full_addr}")
                                                address_corrections[(addr_type, addr)] = corrected_addr
                                            else:
                                                st.error("Indirizzo non trovato. Prova con un altro indirizzo.")
                                    
                                    st.markdown("---")
                                
                                # Pulsante per procedere con le correzioni
                                if st.button("Applica correzioni e calcola tragitto"):
                                    # Crea una copia del DataFrame per applicare le correzioni
                                    corrected_df = filtered_df.copy()
                                    
                                    # Applica le correzioni
                                    for (addr_type, addr), corrected in address_corrections.items():
                                        if addr_type == "casa":
                                            corrected_df.loc[corrected_df["CASA"] == addr, "CASA"] = corrected
                                        else:
                                            corrected_df.loc[corrected_df["LAVORO"] == addr, "LAVORO"] = corrected
                                    
                                    # Aggiorna il DataFrame principale
                                    df.update(corrected_df)
                                    
                                    # Ricarica i dati corretti
                                    casa_address = corrected_df["CASA"].iloc[0]
                                    lavoro_addresses = corrected_df["LAVORO"].unique().tolist()
                                    
                                    # Procedi con il calcolo
                                    st.success("Indirizzi corretti applicati. Calcolo del tragitto...")
                                    st.experimental_rerun()
                            
                            else:
                                # Tutti gli indirizzi sono validi, procedi con il calcolo
                                all_coords = [(lat_casa, lon_casa)]
                                all_addresses = [casa_address]
                                
                                for addr in lavoro_addresses:
                                    lat, lon, _ = geocode_address(addr)
                                    all_coords.append((lat, lon))
                                    all_addresses.append(addr)
                                
                                # Calcola la matrice delle distanze
                                with st.spinner("Calcolo delle distanze tra tutti i punti..."):
                                    distances, durations = calculate_distance_matrix(all_coords)
                                    
                                    if distances is None or durations is None:
                                        st.error("Impossibile calcolare la matrice delle distanze.")
                                        st.stop()
                                
                                # Trova il percorso ottimale
                                with st.spinner("Calcolo del percorso ottimale..."):
                                    # Casa è sempre indice 0
                                    optimal_route = find_optimal_route(distances, 0)
                                    
                                    # Calcola la distanza totale e la durata
                                    total_distance = 0
                                    total_duration = 0
                                    
                                    for i in range(len(optimal_route) - 1):
                                        from_idx = optimal_route[i]
                                        to_idx = optimal_route[i + 1]
                                        total_distance += distances[from_idx, to_idx]
                                        total_duration += durations[from_idx, to_idx]
                                
                                # Mostra i risultati
                                st.subheader("Percorso Ottimale")
                                
                                # Tabella del percorso
                                route_data = []
                                for i in range(len(optimal_route)):
                                    idx = optimal_route[i]
                                    address = all_addresses[idx]
                                    address_type = "Casa" if idx == 0 else "Lavoro"
                                    
                                    # Calcola distanza dal punto precedente (tranne per il primo punto)
                                    distance_from_prev = None
                                    if i > 0:
                                        prev_idx = optimal_route[i-1]
                                        distance_from_prev = distances[prev_idx, idx]
                                    
                                    route_data.append({
                                        "Tappa": i + 1,
                                        "Tipo": address_type,
                                        "Indirizzo": address,
                                        "Distanza dalla tappa precedente (km)": f"{distance_from_prev:.2f}" if distance_from_prev is not None else "-"
                                    })
                                
                                route_df = pd.DataFrame(route_data)
                                st.table(route_df)
                                
                                # Riepilogo totali
                                st.subheader("Riepilogo")
                                st.write(f"**Distanza totale:** {total_distance:.2f} km")
                                st.write(f"**Tempo totale stimato:** {total_duration:.0f} minuti")
                                
                                # Creazione di link per visualizzare l'intero percorso su Google Maps
                                st.subheader("Visualizza su Google Maps")
                                
                                waypoints = []
                                for i in range(1, len(optimal_route) - 1):  # Escludi il primo e l'ultimo (Casa -> Lavori -> Casa)
                                    idx = optimal_route[i]
                                    waypoints.append(f"{all_coords[idx][0]},{all_coords[idx][1]}")
                                
                                # Link a Google Maps con waypoints
                                if waypoints:
                                    start_coords = all_coords[optimal_route[0]]
                                    end_coords = all_coords[optimal_route[-1]]
                                    waypoints_str = "|".join(waypoints)
                                    
                                    google_maps_url = (
                                        f"https://www.google.com/maps/dir/?api=1"
                                        f"&origin={start_coords[0]},{start_coords[1]}"
                                        f"&destination={end_coords[0]},{end_coords[1]}"
                                        f"&waypoints={waypoints_str}"
                                        f"&travelmode=driving"
                                    )
                                    
                                    st.markdown(f"[Apri intero percorso in Google Maps]({google_maps_url})")
                                else:
                                    # Se c'è solo un punto lavoro
                                    google_maps_url = (
                                        f"https://www.google.com/maps/dir/?api=1"
                                        f"&origin={all_coords[optimal_route[0]][0]},{all_coords[optimal_route[0]][1]}"
                                        f"&destination={all_coords[optimal_route[-1]][0]},{all_coords[optimal_route[-1]][1]}"
                                        f"&travelmode=driving"
                                    )
                                    
                                    st.markdown(f"[Apri percorso in Google Maps]({google_maps_url})")
                                
                                # Link singoli per ogni segmento del percorso
                                with st.expander("Link ai segmenti del percorso"):
                                    for i in range(len(optimal_route) - 1):
                                        from_idx = optimal_route[i]
                                        to_idx = optimal_route[i + 1]
                                        
                                        from_coords = all_coords[from_idx]
                                        to_coords = all_coords[to_idx]
                                        
                                        from_address = all_addresses[from_idx]
                                        to_address = all_addresses[to_idx]
                                        
                                        segment_url = (
                                            f"https://www.google.com/maps/dir/?api=1"
                                            f"&origin={from_coords[0]},{from_coords[1]}"
                                            f"&destination={to_coords[0]},{to_coords[1]}"
                                            f"&travelmode=driving"
                                        )
                                        
                                        st.markdown(f"[{from_address} → {to_address}]({segment_url})")
                        else:
                            st.warning(f"Nessun dato trovato per il giorno {giorno_selezionato}.")
                else:
                    st.warning("Nessun giorno trovato nel file CSV.")
        
        with tab2:
            st.subheader("Calcolo Sommatoria Chilometri per Tutti i Giorni")
            
            if not df.empty:
                if st.button("Calcola Totale per Tutti i Giorni"):
                    risultati_totali, distanza_totale_complessiva, durata_totale_complessiva, problematic_addresses = calculate_total_km_for_all_days(df)
                    
                    # Se ci sono indirizzi problematici, mostra un avviso e passa alla tab di correzione
                    if problematic_addresses:
                        st.warning(f"Attenzione: {len(problematic_addresses)} indirizzi non sono stati trovati. Vai alla tab 'Verifica Indirizzi' per correggerli.")
                        
                        # Memorizza gli indirizzi problematici in sessione
                        st.session_state.problematic_addresses = problematic_addresses
                        
                        # Mostra link alla tab di correzione
                        if st.button("Vai alla tab Verifica Indirizzi"):
                            st.session_state.active_tab = "Verifica Indirizzi"
                            st.experimental_rerun()
                    
                    if risultati_totali:
                        # Visualizza tabella con i risultati per ogni giorno
                        st.subheader("Dettaglio per Giorno")
                        risultati_df = pd.DataFrame(risultati_totali)
                        st.table(risultati_df)
                        
                        # Visualizza i totali complessivi
                        st.subheader("Riepilogo Complessivo")
                        st.write(f"**Numero totale di giorni:** {len(risultati_totali)}")
                        st.write(f"**Distanza totale complessiva:** {distanza_totale_complessiva} km")
                        st.write(f"**Tempo totale stimato complessivo:** {durata_totale_complessiva} minuti")
                        
                        # Visualizza un grafico delle distanze per giorno
                        st.subheader("Grafico delle Distanze per Giorno")
                        chart_data = pd.DataFrame({
                            'Giorno': [r['Giorno'] for r in risultati_totali],
                            'Distanza (km)': [r['Distanza Totale (km)'] for r in risultati_totali]
                        })
                        st.bar_chart(chart_data.set_index('Giorno'))
                    else:
                        st.warning("Non è stato possibile calcolare i percorsi per nessun giorno.")
            else:
                st.info("Carica un file CSV con dati validi per calcolare la sommatoria dei chilometri.")
        
        with tab3:
            st.subheader("Verifica e Correzione Indirizzi")
            
            if st.button("Verifica tutti gli indirizzi"):
                # Ottieni tutti gli indirizzi unici dal DataFrame
                casa_addresses = df["CASA"].unique().tolist()
                lavoro_addresses = df["LAVORO"].unique().tolist()
                all_addresses = casa_addresses + lavoro_addresses
                
                # Verifica gli indirizzi
                with st.spinner("Verifica degli indirizzi in corso..."):
                    invalid_addresses = []
                    
                    for addr in casa_addresses:
                        lat, lon, _ = geocode_address(addr)
                        if lat is None:
                            invalid_addresses.append(("casa", addr))
                    
                    for addr in lavoro_addresses:
                        lat, lon, _ = geocode_address(addr)
                        if lat is None:
                            invalid_addresses.append(("lavoro", addr))
                
                # Memorizza gli indirizzi invalidi in session_state
                st.session_state.invalid_addresses = invalid_addresses
                
                # Mostra risultato
                if invalid_addresses:
                    st.warning(f"Trovati {len(invalid_addresses)} indirizzi non validi.")
                else:
                    st.success("Tutti gli indirizzi sono validi!")
            
            # Mostra gli indirizzi problematici se ce ne sono
            if hasattr(st.session_state, "invalid_addresses") and st.session_state.invalid_addresses:
                invalid_addresses = st.session_state.invalid_addresses
                st.subheader("Correzione Indirizzi")
                
                # Dizionario per memorizzare le correzioni
                corrected_addresses = {}
                
                for i, (addr_type, addr) in enumerate(invalid_addresses):
                    st.markdown(f"### {i+1}. Indirizzo {addr_type}: {addr}")
                    
                    # Ottieni suggerimenti
                    with st.spinner(f"Ricerca suggerimenti per {addr}..."):
                        suggestions = get_address_suggestions(addr)
                    
                    # Mostra suggerimenti
                    if suggestions:
                        st.write("**Suggerimenti:**")
                        cols = st.columns(min(3, len(suggestions)))
                        for j, sugg in enumerate(suggestions):
                            with cols[j % len(cols)]:
                                if st.button(f"Usa: {sugg[:30]}...", key=f"sugg_{i}_{j}"):
                                    corrected_addresses[(addr_type, addr)] = sugg
                                    st.success(f"Selezionato: {sugg}")
                    else:
                        st.info("Nessun suggerimento trovato.")
                    
                    # Campo per la correzione manuale
                    corrected = st.text_input(f"Correggi l'indirizzo", value=addr, key=f"corr_{i}")
                    
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        if st.button("Verifica", key=f"verify_{i}"):
                            # Verifica il nuovo indirizzo
                            with st.spinner("Verifica in corso..."):
                                lat, lon, full_addr = geocode_address(corrected)
                                if lat is not None:
                                    st.success(f"Indirizzo valido trovato: {full_addr}")
                                    corrected_addresses[(addr_type, addr)] = corrected
                                else:
                                    st.error("Indirizzo non trovato. Prova con un altro indirizzo o formato.")
                    
                    st.markdown("---")
                
                # Pulsante per applicare tutte le correzioni
                if corrected_addresses:
                    if st.button("Applica tutte le correzioni"):
                        # Crea una copia del DataFrame
                        corrected_df = df.copy()
                        
                        # Applica le correzioni
                        for (addr_type, old_addr), new_addr in corrected_addresses.items():
                            if addr_type == "casa":
                                corrected_df.loc[corrected_df["CASA"] == old_addr, "CASA"] = new_addr
                            else:
                                corrected_df.loc[corrected_df["LAVORO"] == old_addr, "LAVORO"] = new_addr
                        
                        # Aggiorna il DataFrame originale
                        df.update(corrected_df)
                        
                        # Salva il DataFrame corretto nella session_state
                        st.session_state.df = df
                        
                        st.success("Correzioni applicate con successo!")
                        
                        # Verifica che tutti gli indirizzi siano validi dopo le correzioni
                        all_valid = True
                        for (_, old_addr), new_addr in corrected_addresses.items():
                            lat, lon, _ = geocode_address(new_addr)
                            if lat is None:
                                all_valid = False
                                break
                        
                        if all_valid:
                            st.success("Tutti gli indirizzi sono ora validi! Puoi procedere con il calcolo del tragitto.")
                            # Pulisce l'elenco degli indirizzi invalidi
                            st.session_state.invalid_addresses = []
                        else:
                            st.warning("Alcuni indirizzi sono ancora invalidi. Controlla nuovamente.")
            
            # Mostra gli indirizzi problematici trovati durante il calcolo complessivo
            elif hasattr(st.session_state, "problematic_addresses") and st.session_state.problematic_addresses:
                problematic_addresses = st.session_state.problematic_addresses
                st.subheader("Indirizzi problematici trovati durante il calcolo")
                
                # Raggruppa gli indirizzi per tipo e giorno
                grouped_addresses = {}
                for addr_type, addr, giorno in problematic_addresses:
                    key = (addr_type, giorno)
                    if key not in grouped_addresses:
                        grouped_addresses[key] = []
                    grouped_addresses[key].append(addr)
                
                # Mostra gli indirizzi raggruppati
                for (addr_type, giorno), addresses in grouped_addresses.items():
                    st.markdown(f"### {addr_type.capitalize()} - Giorno {giorno}")
                    for i, addr in enumerate(addresses):
                        st.write(f"{i+1}. {addr}")
                
                # Pulsante per andare alla correzione manuale
                if st.button("Correggi questi indirizzi"):
                    # Converti problematic_addresses nel formato di invalid_addresses
                    invalid_addresses = [(addr_type, addr) for addr_type, addr, _ in problematic_addresses]
                    # Rimuovi duplicati
                    invalid_addresses = list(set(invalid_addresses))
                    st.session_state.invalid_addresses = invalid_addresses
                    st.experimental_rerun()
            else:
                st.info("Clicca su 'Verifica tutti gli indirizzi' per iniziare il processo di verifica.")

else:
    st.info("Carica un file CSV con colonne 'CASA', 'LAVORO' e 'GIORNO' per iniziare.")
    
    # Aggiungi opzione per creare un nuovo file
    if st.button("Crea nuovo file"):
        # Crea un DataFrame vuoto con le colonne necessarie
        df = pd.DataFrame(columns=["CASA", "LAVORO", "GIORNO"])
        
        # Aggiungi interfaccia per inserire i dati
        with st.form("create_new_form"):
            casa = st.text_input("Indirizzo di casa")
            lavoro = st.text_input("Indirizzo di lavoro")
            giorno = st.date_input("Giorno", datetime.now())
            
            submit = st.form_submit_button("Aggiungi")
            
            if submit and casa and lavoro:
                new_row = pd.DataFrame({
                    "CASA": [casa], 
                    "LAVORO": [lavoro], 
                    "GIORNO": [giorno.strftime("%d/%m/%Y")]
                })
                df = pd.concat([df, new_row], ignore_index=True)
                
                # Scarica il file creato
                csv = df.to_csv(sep=";", index=False)
                st.download_button(
                    label="Scarica CSV",
                    data=csv,
                    file_name="indirizzi.csv",
                    mime="text/csv"
                )
                
                st.success("File creato con successo!")
                st.dataframe(df)

# Aggiungi istruzioni d'uso
with st.expander("Come usare questa applicazione"):
    st.markdown("""
    ### Istruzioni per l'uso
    
    1. **Carica il tuo file CSV** con le colonne CASA, LAVORO e GIORNO.
    2. **Seleziona un giorno** dalla lista dei giorni disponibili oppure usa la tab "Riepilogo Totale" per calcolare i km totali per tutti i giorni.
    3. **Premi 'Calcola Tragitto Ottimale'** per vedere il percorso ottimale che inizia da casa, passa per tutti i luoghi di lavoro e torna a casa.
    4. **Premi 'Calcola Totale per Tutti i Giorni'** nella tab "Riepilogo Totale" per vedere la sommatoria dei chilometri per tutti i giorni.
    5. **Usa la tab 'Verifica Indirizzi'** per controllare e correggere eventuali indirizzi problematici.
    
    ### Formato del file CSV
    
    Il file CSV deve avere le seguenti colonne:
    - **CASA**: indirizzo completo dell'abitazione
    - **LAVORO**: indirizzo completo del posto di lavoro
    - **GIORNO**: data nel formato GG/MM/AAAA
    
    Esempio:
    ```
    CASA;LAVORO;GIORNO
    Via Roma 1, Milano;Via Dante 15, Milano;01/05/2025
    Via Roma 1, Milano;Via Montenapoleone 8, Milano;01/05/2025
    Via Roma 1, Milano;Piazza Duomo 1, Milano;01/05/2025
    ```
    
    ### Note sulla correzione degli indirizzi
    
    - Se un indirizzo non viene trovato, l'applicazione ti permetterà di correggerlo.
    - Per ogni indirizzo problematico, l'app suggerirà indirizzi alternativi quando possibile.
    - Puoi verificare individualmente ciascun indirizzo cliccando sul pulsante "Verifica".
    - Una volta corretti tutti gli indirizzi, potrai applicare le correzioni e procedere con il calcolo del tragitto.
    """)

# Footer con informazioni
st.markdown("---")
st.markdown("Applicazione creata con Streamlit. Utilizza le API gratuite di OpenStreetMap e OSRM.")
