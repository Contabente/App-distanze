import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime
import itertools
import os

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
            return lat, lon
        else:
            return None
    except Exception as e:
        st.error(f"Errore durante la geocodifica: {e}")
        return None

# Funzione per cercare suggerimenti per indirizzi non trovati
def find_address_suggestions(address):
    try:
        base_url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 5  # Otteniamo fino a 5 suggerimenti
        }
        headers = {
            "User-Agent": "TragittoCalculator/1.0"
        }
        
        response = requests.get(base_url, params=params, headers=headers)
        data = response.json()
        
        suggestions = []
        for item in data:
            # Prendiamo l'indirizzo completo formattato da OSM
            suggestions.append({
                "display_name": item["display_name"],
                "lat": float(item["lat"]),
                "lon": float(item["lon"])
            })
        
        return suggestions
    except Exception as e:
        st.error(f"Errore durante la ricerca di suggerimenti: {e}")
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
                    st.error(f"Impossibile calcolare la distanza tra i punti {i} e {j}")
                    return None, None
    
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

# Funzione per calcolare e visualizzare la sommatoria dei km per tutti i giorni
def calculate_total_km_for_all_days(df):
    giorni_disponibili = df["GIORNO"].unique().tolist()
    risultati_totali = []
    distanza_totale_complessiva = 0
    durata_totale_complessiva = 0

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
                if coords_casa is None:
                    st.error(f"Impossibile geocodificare l'indirizzo di casa per il giorno {giorno}: {casa_address}")
                    
                    # Cerca suggerimenti per l'indirizzo di casa
                    suggestions = find_address_suggestions(casa_address)
                    if suggestions:
                        st.warning(f"Suggerimenti per l'indirizzo di casa ({giorno}):")
                        for i, sugg in enumerate(suggestions[:3]):  # Limitiamo a 3 suggerimenti per non sovraccaricare
                            if st.button(f"Usa: {sugg['display_name']}", key=f"casa_{giorno}_{i}"):
                                coords_casa = (sugg["lat"], sugg["lon"])
                                st.success(f"Indirizzo di casa sostituito con: {sugg['display_name']}")
                                # Aggiorniamo anche il dataframe
                                df.loc[(df["GIORNO"] == giorno) & (df["CASA"] == casa_address), "CASA"] = sugg["display_name"]
                    
                    if coords_casa is None:
                        continue
                
                coords_lavoro_list = []
                geocode_failed = False
                
                for addr in lavoro_addresses:
                    coords = geocode_address(addr)
                    if coords is None:
                        st.error(f"Impossibile geocodificare l'indirizzo di lavoro per il giorno {giorno}: {addr}")
                        
                        # Cerca suggerimenti
                        suggestions = find_address_suggestions(addr)
                        if suggestions:
                            st.warning(f"Suggerimenti per l'indirizzo di lavoro '{addr}' ({giorno}):")
                            for i, sugg in enumerate(suggestions[:3]):  # Limitiamo a 3 suggerimenti
                                if st.button(f"Usa: {sugg['display_name']}", key=f"lavoro_{giorno}_{addr}_{i}"):
                                    coords = (sugg["lat"], sugg["lon"])
                                    st.success(f"Indirizzo di lavoro sostituito con: {sugg['display_name']}")
                                    # Aggiorniamo anche il dataframe
                                    df.loc[(df["GIORNO"] == giorno) & (df["LAVORO"] == addr), "LAVORO"] = sugg["display_name"]
                        
                        if coords is None:
                            geocode_failed = True
                            break
                    
                    coords_lavoro_list.append(coords)
                
                if geocode_failed:
                    st.warning(f"Risolvi gli indirizzi problematici per il giorno {giorno} e riprova.")
                    continue
                
                # Crea lista completa di coordinate con casa come prima posizione
                all_coords = [coords_casa] + coords_lavoro_list
                
                # Calcola la matrice delle distanze
                distances, durations = calculate_distance_matrix(all_coords)
                
                if distances is None or durations is None:
                    st.error(f"Impossibile calcolare la matrice delle distanze per il giorno {giorno}.")
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
    
    return risultati_totali, round(distanza_totale_complessiva, 2), round(durata_totale_complessiva, 0)

# Creiamo una sessione state per mantenere il dataframe tra i refresh
if 'df' not in st.session_state:
    st.session_state.df = None
if 'indirizzo_sostituito' not in st.session_state:
    st.session_state.indirizzo_sostituito = False

# Sezione per il caricamento del file
uploaded_file = st.file_uploader("Carica il tuo file CSV", type=["csv"])

if uploaded_file:
    # Carica il file solo se è un nuovo upload o se non l'abbiamo ancora caricato
    if st.session_state.df is None:
        df = load_csv(uploaded_file)
        if df is not None:
            st.session_state.df = df
    else:
        df = st.session_state.df
    
    if df is not None:
        st.success("File caricato con successo!")
        
        # Mostra anteprima dei dati
        st.subheader("Anteprima dei dati")
        st.dataframe(df.head())
        
        # Aggiungi tab per separare le funzionalità
        tab1, tab2 = st.tabs(["Calcolo Giornaliero", "Riepilogo Totale"])
        
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
                                coords_casa = geocode_address(casa_address)
                                
                                if coords_casa is None:
                                    st.error(f"Impossibile geocodificare l'indirizzo di casa: {casa_address}")
                                    
                                    # Cerca suggerimenti
                                    suggestions = find_address_suggestions(casa_address)
                                    if suggestions:
                                        st.warning("Suggerimenti per l'indirizzo di casa:")
                                        suggestion_options = [sugg["display_name"] for sugg in suggestions]
                                        selected_suggestion = st.selectbox("Seleziona un indirizzo alternativo:", suggestion_options)
                                        
                                        if st.button("Usa questo indirizzo"):
                                            # Trova il suggerimento selezionato
                                            for sugg in suggestions:
                                                if sugg["display_name"] == selected_suggestion:
                                                    coords_casa = (sugg["lat"], sugg["lon"])
                                                    st.success(f"Indirizzo di casa sostituito con: {selected_suggestion}")
                                                    break
                                    
                                    # Se ancora non abbiamo coordinate valide, fermiamo l'esecuzione
                                    if coords_casa is None:
                                        st.stop()
                                
                                coords_lavoro_list = []
                                addresses_with_issues = []
                                
                                for i, addr in enumerate(lavoro_addresses):
                                    coords = geocode_address(addr)
                                    if coords is None:
                                        addresses_with_issues.append((i, addr))
                                    else:
                                        coords_lavoro_list.append(coords)
                                
                                # Gestisci gli indirizzi problematici
                                if addresses_with_issues:
                                    for idx, problematic_addr in addresses_with_issues:
                                        st.error(f"Impossibile geocodificare l'indirizzo di lavoro: {problematic_addr}")
                                        
                                        # Cerca suggerimenti
                                        suggestions = find_address_suggestions(problematic_addr)
                                        if suggestions:
                                            st.warning(f"Suggerimenti per l'indirizzo '{problematic_addr}':")
                                            suggestion_options = [sugg["display_name"] for sugg in suggestions]
                                            col_select, col_button = st.columns([3, 1])
                                            
                                            with col_select:
                                                suggestion_key = f"suggestion_{idx}"
                                                selected_suggestion = st.selectbox(
                                                    "Seleziona un indirizzo alternativo:", 
                                                    suggestion_options,
                                                    key=suggestion_key
                                                )
                                            
                                            with col_button:
                                                button_key = f"use_button_{idx}"
                                                if st.button("Usa questo", key=button_key):
                                                    # Trova il suggerimento selezionato
                                                    for sugg in suggestions:
                                                        if sugg["display_name"] == selected_suggestion:
                                                            new_coords = (sugg["lat"], sugg["lon"])
                                                            coords_lavoro_list.append(new_coords)
                                                            st.success(f"Indirizzo sostituito con: {selected_suggestion}")
                                                            
                                                            # Aggiorna il dataframe per future esecuzioni
                                                            df.loc[df["LAVORO"] == problematic_addr, "LAVORO"] = selected_suggestion
                                                            break
                                    
                                    # Verifica se abbiamo risolto tutti i problemi
                                    if len(coords_lavoro_list) != len(lavoro_addresses):
                                        remaining_issues = len(lavoro_addresses) - len(coords_lavoro_list)
                                        st.warning(f"Ci sono ancora {remaining_issues} indirizzi non risolti. Correggi gli indirizzi e riprova.")
                                        st.stop()
                            
                            # Crea lista completa di coordinate con casa come prima posizione
                            all_coords = [coords_casa] + coords_lavoro_list
                            all_addresses = [casa_address] + lavoro_addresses
                            
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
                    risultati_totali, distanza_totale_complessiva, durata_totale_complessiva = calculate_total_km_for_all_days(df)
                    
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
    5. **Se un indirizzo non viene trovato**, l'applicazione ti suggerirà alternative. Puoi selezionare l'indirizzo corretto tra i suggerimenti e usarlo per il calcolo.
    6. **Dopo aver corretto degli indirizzi**, puoi scaricare il file CSV aggiornato utilizzando il pulsante in fondo alla pagina.
    
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
    
    ### Note
    - L'applicazione calcola il percorso ottimale partendo da casa, passando per tutti i luoghi di lavoro e tornando a casa.
    - Per ogni giorno, puoi avere più luoghi di lavoro da visitare.
    - L'applicazione utilizza API gratuite (OpenStreetMap e OSRM) per la geocodifica e il calcolo del percorso.
    - Il calcolo della sommatoria totale può richiedere tempo se ci sono molti giorni/indirizzi.
    """)

# Opzione per scaricare il CSV aggiornato con gli indirizzi corretti
if st.session_state.df is not None:
    st.markdown("---")
    st.subheader("Scarica il file CSV aggiornato")
    st.write("Se hai corretto degli indirizzi, puoi scaricare il file CSV aggiornato:")
    
    # Crea il CSV aggiornato
    csv_aggiornato = st.session_state.df.to_csv(sep=";", index=False)
    
    # Bottone per scaricare
    st.download_button(
        label="Scarica CSV aggiornato",
        data=csv_aggiornato,
        file_name="indirizzi_aggiornati.csv",
        mime="text/csv"
    )

# Footer con informazioni
st.markdown("---")
st.markdown("Applicazione creata con Streamlit. Utilizza le API gratuite di OpenStreetMap e OSRM.")
