# data_manager.py - UNIFIED VERSION med v1.7 implementation
"""
Unified Data Manager for GEOseis 2.0 - Tilbage til v1.7's velfungerende approach
================================================================================

VIGTIGE ÆNDRINGER FRA SESSION 13:
1. Station søgning bruger ORIGINAL v1.7 geografisk fordeling
2. Validerer KUN udvalgte stationer, ikke alle
3. Returnerer arrival times som SEKUNDER (float) ikke UTCDateTime strings
4. Pragmatisk approach: vis data selv uden response
5. Alt samlet i én fil for bedre performance

PRINCIPPER:
- Hastighed over perfektion
- Vis data frem for at fejle
- Geografisk fordeling prioriteres
- Minimal validation
"""

import streamlit as st
from obspy.clients.fdsn import Client
from obspy import UTCDateTime, Stream
from obspy.taup import TauPyModel
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees, locations2degrees
import numpy as np
import pandas as pd
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
import warnings
import gc
import re
import threading
from typing import Dict, List, Tuple, Optional, Any
from io import BytesIO
import xlsxwriter

# Suppress warnings
warnings.filterwarnings('ignore')

def get_cached_taup_model():
    """Returnerer cached TauPyModel instans"""
    if 'taup_model' not in st.session_state:
        print("Creating new TauPyModel instance...")
        st.session_state.taup_model = TauPyModel(model="iasp91")
    return st.session_state.taup_model

def ensure_utc_datetime(time_obj):
    """Konverterer forskellige tidsformater til UTCDateTime"""
    if time_obj is None:
        return None
    
    if isinstance(time_obj, UTCDateTime):
        return time_obj
    
    if isinstance(time_obj, str):
        # Håndter ISO format
        if 'T' in time_obj:
            return UTCDateTime(time_obj)
        # Håndter andre string formater
        return UTCDateTime(time_obj)
    
    if isinstance(time_obj, (int, float)):
        return UTCDateTime(time_obj)
    
    if hasattr(time_obj, 'timestamp'):
        return UTCDateTime(time_obj.timestamp())
    
    # Sidste forsøg
    return UTCDateTime(str(time_obj))

class StreamlinedDataManager:
    """
    Unified data manager med v1.7's velfungerende implementation.
    
    VIGTIGE ÆNDRINGER:
    - search_stations bruger original geografisk fordeling
    - Minimal validation - kun udvalgte stationer
    - Arrival times som sekunder
    - Pragmatisk waveform download
    """
    
    def __init__(self):
        """Initialiserer data manager med cached komponenter"""
        # IRIS client
        self.client = None
        self.connect_to_iris()
        
        # Cached TauP model
        self.taup_model = get_cached_taup_model()
        
        # Processor reference - sættes eksternt hvis nødvendigt
        self.processor = None
        
        # Initialize caches hvis ikke eksisterer
        if 'earthquake_cache' not in st.session_state:
            st.session_state.earthquake_cache = {}
        if 'station_cache' not in st.session_state:
            st.session_state.station_cache = {}
        if 'waveform_cache' not in st.session_state:
            st.session_state.waveform_cache = {}
        if 'inventory_cache' not in st.session_state:
            st.session_state.inventory_cache = {}
    
    # ========================================
    # IRIS CONNECTION
    # ========================================
    
    def connect_to_iris(self):
        """Opretter forbindelse til IRIS med retries"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"Connecting to IRIS... (attempt {attempt + 1}/{max_retries})")
                self.client = Client("IRIS", timeout=30)
                # Test forbindelse
                test_time = UTCDateTime.now()
                self.client.get_stations(
                    network="IU", station="ANMO", 
                    starttime=test_time - 86400,
                    endtime=test_time,
                    level="station"
                )
                print("✓ IRIS connection established")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    st.error(f"Kunne ikke oprette forbindelse til IRIS: {str(e)}")
                    return False
        return False
    
    # ========================================
    # EARTHQUAKE SEARCH
    # ========================================
    
    def fetch_latest_earthquakes(self, magnitude_range=(6.0, 10.0), 
                                year_range=None, depth_range=(0, 700),
                                limit=500, days=None):
        """
        Henter seneste jordskælv fra IRIS.
        Returnerer dictionaries med ISO timestamp strings.
        """
        try:
            # Tidsramme
            if days:
                endtime = UTCDateTime.now()
                starttime = endtime - (days * 86400)
            elif year_range:
                starttime = UTCDateTime(year_range[0], 1, 1)
                endtime = UTCDateTime(year_range[1], 12, 31, 23, 59, 59)
            else:
                endtime = UTCDateTime.now()
                starttime = endtime - (180 * 86400)  # 180 dage default
            
            # Check cache
            cache_key = f"{magnitude_range}_{year_range}_{depth_range}_{limit}_{starttime}_{endtime}"
            cached = self._check_cache('earthquake_cache', cache_key)
            if cached:
                return cached
            
            print(f"Searching earthquakes: M{magnitude_range[0]}-{magnitude_range[1]}, "
                  f"depth {depth_range[0]}-{depth_range[1]} km")
            
            # VIGTIG: Brug dybde i KILOMETER
            catalog = self.client.get_events(
                starttime=starttime,
                endtime=endtime,
                minmagnitude=magnitude_range[0],
                maxmagnitude=magnitude_range[1],
                mindepth=depth_range[0],    # KM
                maxdepth=depth_range[1],    # KM
                orderby="time",  # IRIS accepterer kun: time, time-asc, magnitude, magnitude-asc
                limit=limit
            )
            
            earthquakes = self._process_catalog(catalog)
            
            # Update cache
            if earthquakes:
                self._update_cache('earthquake_cache', cache_key, earthquakes)
            
            return earthquakes
            
        except Exception as e:
            st.error(f"Fejl ved jordskælvssøgning: {str(e)}")
            print(f"Earthquake search error: {e}")
            return []
    
    def get_latest_significant_earthquakes(self, min_magnitude=6.5, days=365):
        """Quick method til at hente seneste store jordskælv"""
        return self.fetch_latest_earthquakes(
            magnitude_range=(min_magnitude, 10.0),
            days=days,
            limit=500
        )
    
    def _process_catalog(self, catalog):
        """
        Process ObsPy catalog til list af dictionaries.
        VIGTIG: Returnerer ISO timestamp strings, IKKE obspy_event!
        """
        earthquakes = []
        
        # Sortér catalog efter tid (nyeste først) siden IRIS kun giver "time" (ældste først)
        sorted_events = sorted(catalog, key=lambda e: e.preferred_origin().time, reverse=True)
        
        for event in sorted_events:
            try:
                # Få preferred origin og magnitude
                origin = event.preferred_origin() or event.origins[0]
                magnitude = event.preferred_magnitude() or event.magnitudes[0]
                
                # Lokation beskrivelse
                if event.event_descriptions:
                    location = event.event_descriptions[0].text
                else:
                    location = f"Lat: {origin.latitude:.2f}, Lon: {origin.longitude:.2f}"
                
                eq_dict = {
                    'time': origin.time.isoformat(),  # ISO string format!
                    'latitude': float(origin.latitude),
                    'longitude': float(origin.longitude),
                    'depth': float(origin.depth / 1000.0) if origin.depth else 10.0,  # Til km
                    'magnitude': float(magnitude.mag),
                    'magnitude_type': str(magnitude.magnitude_type) if magnitude.magnitude_type else 'M',
                    'location': location,
                    'event_id': str(event.resource_id).split('/')[-1]
                }
                
                # IKKE inkluderet: 'obspy_event' - dette forårsager problemer!
                
                earthquakes.append(eq_dict)
                
            except Exception as e:
                print(f"Error processing event: {e}")
                continue
        
        return earthquakes
    
    # ========================================
    # STATION SEARCH - 
    # ========================================
    def search_stations(self, earthquake, min_distance_km=500, max_distance_km=3000, target_stations=3):
        """
        FORBEDRET version - BEVARER alle dine hastigheds-optimeringer
        Tilføjer kun premium network prioritering og fallback tracking
        """
        
        # BEVAR din eksisterende execution guard
        execution_key = f"exec_{earthquake.get('time')}_{min_distance_km}_{max_distance_km}_{target_stations}"
        
        # BEVAR din eksisterende cache check
        if hasattr(st.session_state, 'station_results'):
            if execution_key in st.session_state.station_results:
                cached = st.session_state.station_results[execution_key]
                print(f"✅ CACHED: Returning {len(cached)} cached stations")
                return cached
        else:
            st.session_state.station_results = {}
        
        # BEVAR din eksisterende duplicate guard
        if hasattr(st.session_state, 'executing_search'):
            if st.session_state.executing_search == execution_key:
                print(f"🔄 DUPLICATE: Search already executing, skipping this call")
                return []
        
        # Start execution
        st.session_state.executing_search = execution_key
        print(f"🚀 FORBEDRET SEARCH: Starting search for {target_stations} stations")
        
        try:
            # BEVAR din eksisterende earthquake data processing
            eq_lat = earthquake['latitude']
            eq_lon = earthquake['longitude']
            eq_depth = earthquake.get('depth', 10.0)
            eq_time = ensure_utc_datetime(earthquake['time'])  # Brug din eksisterende funktion
            
            if not eq_time:
                print(f"❌ Invalid earthquake time")
                return []
            
            # BEVAR din eksisterende IRIS connection
            if not hasattr(self, 'client') or self.client is None:
                self.connect_to_iris()
            
            print(f"📡 Requesting stations from IRIS...")
            
            # BEVAR din eksisterende HURTIG IRIS request - kun udvidet netværk listen
            inventory = self.client.get_stations(
                network="IU,II,G,GE,GT,IC",  # Udvidet til flere premium networks
                station="*",
                level="station",  # BEVAR din station level for hastighed
                starttime=eq_time - 86400,
                endtime=eq_time + 86400,
                includerestricted=False,
                matchtimeseries=False
            )
            
            if not inventory:
                print(f"❌ No inventory returned from IRIS")
                return []
            
            # med forbedret prioritering
            all_stations = self._process_stations(
                inventory, eq_lat, eq_lon, eq_depth, eq_time,
                min_distance_km, max_distance_km
            )
            
            if not all_stations:
                print(f"❌ No stations found in distance range")
                return []
            
            # NY: PREMIUM NETWORK PRIORITERING 
            all_stations.sort(key=lambda x: (
                x.get('network_priority', 99),     # ABSOLUT prioritet: Netværk kvalitet
                0 if x.get('network_priority', 99) <= 2 else x['distance_km'] // 500,  # Kun afstand for premium networks
                x.get('channel_priority', 99),     # Channel kvalitet
                x['distance_km']                   # Final tiebreaker
            ))
            
            # BEVAR din eksisterende selection logic
            selected_stations = all_stations[:target_stations]
            
            print(f"🎯 SELECTED: {len(selected_stations)} stations")
            for s in selected_stations:
                print(f"  {s['network']}.{s['station']} - {s['distance_km']:.0f}km (NP:{s.get('network_priority', 99)})")
            
            # BEVAR din eksisterende cache
            st.session_state.station_results[execution_key] = selected_stations
            print(f"💾 CACHED: Stored {len(selected_stations)} stations")
            
            return selected_stations
            
        except Exception as e:
            print(f"❌ Search error: {e}")
            return []
        
        finally:
            # BEVAR din eksisterende cleanup
            if hasattr(st.session_state, 'executing_search'):
                if st.session_state.executing_search == execution_key:
                    del st.session_state.executing_search
                    print(f"🔓 EXECUTION: Cleared execution flag")
 
    def clear_search_states(self):
        """
        Ryd alle search-relaterede states
        """
        states_to_clear = [
            'searching_stations', 'station_list', 'selected_station',
            'simple_stations', 'search_in_progress', 'active_searches'
        ]
        
        for state in states_to_clear:
            if hasattr(st.session_state, state):
                delattr(st.session_state, state)
                print(f"Cleared: {state}")
        
        print("✅ All search states cleared")

    def clear_all_search_cache_debug(self):
        """
        Rydder AL søgning cache og viser hvad der bliver ryddet
        """
        print("🧹 CLEARING ALL SEARCH CACHE:")
        
        if hasattr(st.session_state, 'search_in_progress'):
            print(f"  - search_in_progress: {len(st.session_state.search_in_progress)} entries")
            st.session_state.search_in_progress = {}
        
        if hasattr(st.session_state, 'active_searches'):
            print(f"  - active_searches: {st.session_state.active_searches}")
            st.session_state.active_searches = set()
        
        # Ryd andre mulige search states
        for key in list(st.session_state.keys()):
            if 'search' in key.lower() or 'station' in key.lower():
                if key not in ['selected_station', 'station_list']:  # Bevar vigtige states
                    print(f"  - Clearing: {key}")
                    del st.session_state[key]
        
        print("✅ ALL SEARCH CACHE CLEARED")


    def debug_session_state(self):
        """
        Viser alle session state keys relateret til search
        """
        print("🔍 SESSION STATE DEBUG:")
        search_related = {}
        
        for key, value in st.session_state.items():
            if any(word in key.lower() for word in ['search', 'station', 'cache']):
                if isinstance(value, (dict, list, set)):
                    search_related[key] = f"{type(value).__name__}({len(value)})"
                else:
                    search_related[key] = f"{type(value).__name__}: {value}"
        
        for key, value in search_related.items():
            print(f"  - {key}: {value}")

    def _process_stations(self, inventory, eq_lat, eq_lon, eq_depth, eq_time,
                                            min_distance_km, max_distance_km):
        """
        FORBEDRET version - BEVARER din ULTRA HURTIG processing
        Tilføjer kun network prioritering - INGEN nye langsomme beregninger
        """
        stations = []
        
        # NY: FORBEDRET NETWORK PRIORITERING - samme hastighed som din eksisterende
        network_scores = {
            'IU': 1,    # Global Seismographic Network - BEDSTE
            'II': 1,    # Global Seismographic Network - BEDSTE  
            'G': 2,     # GEOSCOPE - Meget god
            'GE': 2,    # GEOFON - Meget god
            'GT': 3,    # Global Telemetered - God
            'IC': 4,    # New China Digital Seismograph Network - OK
            'CU': 5,    # Caribbean Network - OK
            'US': 6,    # United States National Seismic Network - Variabel
            'TA': 7,    # USArray Transportable Array - Midlertidig
            'N4': 8     # USArray - Specialiseret
        }
        
        # BEVAR din eksisterende channel prioritering
        channel_scores = {
            'BHZ': 1, 'BHE': 1, 'BHN': 1,  # Broadband High gain - BEDST
            'HHZ': 2, 'HHE': 2, 'HHN': 2,  # High broadband - God
            'SHZ': 3, 'SHE': 3, 'SHN': 3,  # Short period - OK
            'LHZ': 4, 'LHE': 4, 'LHN': 4   # Long period - Speciel
        }
        
        # BEVAR din cached TauP model - INGEN ny model creation
        if not hasattr(self, 'taup_model') or self.taup_model is None:
            self.taup_model = get_cached_taup_model()  # Brug din cached version
        
        for network in inventory:
            for station in network:
                try:
                    # BEVAR din eksisterende distance beregning - INGEN ændringer
                    distance_m, azimuth, _ = gps2dist_azimuth(
                        eq_lat, eq_lon, station.latitude, station.longitude
                    )
                    distance_km = distance_m / 1000.0
                    distance_deg = distance_km / 111.32
                    
                    # BEVAR din eksisterende distance filter
                    if not (min_distance_km <= distance_km <= max_distance_km):
                        continue
                    
                    # NY: Tilføj network prioritering - O(1) lookup, ingen performance impact
                    net_priority = network_scores.get(network.code, 99)
                    
                    # BEVAR din eksisterende channel processing
                    best_channel_priority = 99
                    if len(station.channels) > 0:
                        for channel in station.channels:
                            chan_priority = channel_scores.get(channel.code, 99)
                            best_channel_priority = min(best_channel_priority, chan_priority)
                    
                    # BEVAR din eksisterende arrival times calculation
                    # (brug din eksisterende hurtige metode - TauP eller simple estimates)
                    p_arrival = s_arrival = 0
                    if self.taup_model and distance_deg > 0:
                        try:
                            arrivals = self.taup_model.get_travel_times(
                                source_depth_in_km=eq_depth,
                                distance_in_degree=distance_deg,
                                phase_list=["P", "S"]
                            )
                            for arr in arrivals:
                                if arr.name == 'P' and p_arrival == 0:
                                    p_arrival = arr.time
                                elif arr.name == 'S' and s_arrival == 0:
                                    s_arrival = arr.time
                        except:
                            pass
                    
                    # BEVAR din eksisterende surface wave estimates
                    love_arrival = distance_km / 4.5      # ~4.5 km/s for Love bølger
                    rayleigh_arrival = distance_km / 3.5  # ~3.5 km/s for Rayleigh bølger
                    surface_arrival = rayleigh_arrival    # Default til Rayleigh
                    
                    # BEVAR din eksisterende station data structure - kun tilføj prioritering
                    station_data = {
                        'network': network.code,
                        'station': station.code,
                        'latitude': station.latitude,
                        'longitude': station.longitude,
                        'distance_deg': round(distance_deg, 2),
                        'distance_km': round(distance_km, 1),
                        'azimuth': round(azimuth, 1),
                        'p_arrival': round(p_arrival, 3) if p_arrival > 0 else None,
                        's_arrival': round(s_arrival, 3) if s_arrival > 0 else None,
                        'love_arrival': round(love_arrival, 3),
                        'rayleigh_arrival': round(rayleigh_arrival, 3),
                        'surface_arrival': round(surface_arrival, 3),
                        'network_priority': net_priority,        # NY: Tilføjer prioritering
                        'channel_priority': best_channel_priority, # NY: Tilføjer channel prioritering
                        'data_source': 'ULTRA_FAST_FORBEDRET',   # NY: Markering
                        'operational_years': getattr(station, 'end_date', None) is None and 1 or 0
                    }
                    
                    stations.append(station_data)
                    
                except Exception as e:
                    print(f"Error processing station {network.code}.{station.code}: {e}")
                    continue
        
        print(f"Processed {len(stations)} stations with FORBEDRET prioritering (samme hastighed)")
        return stations

    def handle_failed_station_download(self, failed_station, earthquake):
        """
        Håndterer failed station download med smart fallback
        INGEN performance impact - kun tracking og re-search
        """
        print(f"🔄 HANDLING FAILED STATION: {failed_station['network']}.{failed_station['station']}")
        
        # Initialize failed stations tracking
        if 'failed_station_downloads' not in st.session_state:
            st.session_state.failed_station_downloads = set()
        
        # Marker station som failed
        failed_key = f"{failed_station['network']}.{failed_station['station']}"
        st.session_state.failed_station_downloads.add(failed_key)
        print(f"📝 MARKED AS FAILED: {failed_key}")
        
        # Søg nye stationer med failed station ekskluderet
        return self.search_stations_excluding_failed(
            earthquake, 
            st.session_state.get('search_min_dist', 1500),
            st.session_state.get('search_max_dist', 3000),
            st.session_state.get('search_target_stations', 3)
    )

    def search_stations_excluding_failed(self, earthquake, min_distance_km, max_distance_km, target_stations):
        """
        Søger stationer men ekskluderer failed ones
        BRUGER din eksisterende search_stations - kun filtrering bagefter
        """
        print(f"🔍 SEARCHING STATIONS (excluding failed ones)")
        
        # Kør din eksisterende station search - INGEN ændringer
        all_stations = self.search_stations(earthquake, min_distance_km, max_distance_km, target_stations * 2)
        
        if not all_stations:
            return []
        
        # Filtrer failed stations ud - O(n) operation, minimal performance impact
        failed_stations = st.session_state.get('failed_station_downloads', set())
        available_stations = []
        
        for station in all_stations:
            station_key = f"{station['network']}.{station['station']}"
            if station_key not in failed_stations:
                available_stations.append(station)
        
        print(f"✅ AVAILABLE STATIONS: {len(available_stations)} (filtered from {len(all_stations)})")
        
        # Returnér kun target antal
        return available_stations[:target_stations]

    def clear_failed_stations(self):
        """
        Rydder failed stations tracking - nyttig til debugging
        INGEN performance impact
        """
        if 'failed_station_downloads' in st.session_state:
            failed_count = len(st.session_state.failed_station_downloads)
            st.session_state.failed_station_downloads = set()
            print(f"✅ CLEARED: {failed_count} failed stations")
        else:
            print("✅ CLEARED: No failed stations to clear")

    def debug_failed_stations(self):
        """
        Debug funktion til at se failed stations
        INGEN performance impact
        """
        failed = st.session_state.get('failed_station_downloads', set())
        print(f"🔍 FAILED STATIONS DEBUG: {len(failed)} failed stations")
        for station in failed:
            print(f"  - {station}")

    def get_station_fallback_stats(self):
        """
        Statistik over fallback system  
        INGEN performance impact
        """
        failed = st.session_state.get('failed_station_downloads', set())
        total_searched = len(st.session_state.get('station_results', {}))
        
        return {
            'failed_stations': len(failed),
            'total_searches': total_searched,
            'success_rate': (total_searched - len(failed)) / max(total_searched, 1) * 100
        }


    def debug_double_calls(self):
        """
        Debug funktion til at finde hvornår search_stations kaldes to gange
        """
        original_method = self.search_stations
        call_count = {'count': 0}
        
        def wrapped_method(*args, **kwargs):
            call_count['count'] += 1
            import traceback
            print(f"🔍 search_stations call #{call_count['count']}:")
            # Vis call stack
            for line in traceback.format_stack()[-3:-1]:
                print(f"  {line.strip()}")
            return original_method(*args, **kwargs)
        
        self.search_stations = wrapped_method
        print("✅ Double call debugging enabled")


    def clear_search_state(self):
        """
        Rydder alle search states for at forhindre dobbelt kald
        """
        st.session_state.pop('search_in_progress', None)
        st.session_state.pop('active_searches', None)
        st.session_state.pop('searching_stations', None)
        print("✅ Cleared all search state")


    def clear_station_search_cache(self):
        """
        Hjælpefunktion til at rydde station search cache
        """
        if 'search_in_progress' in st.session_state:
            st.session_state.search_in_progress = {}
            print("DEBUG: Ryddet search_in_progress cache")


    def get_search_cache_status(self):
        """
        Debug funktion til at se cache status
        """
        if 'search_in_progress' in st.session_state:
            cache = st.session_state.search_in_progress
            print(f"DEBUG: Search cache har {len(cache)} entries:")
            for key, value in cache.items():
                print(f"  {key}: {len(value) if isinstance(value, list) else type(value)} items")
        else:
            print("DEBUG: Ingen search cache")


    def calculate_detailed_surface_waves_for_station(self, station, earthquake):
        """
        Beregner detaljerede overfladebølgedata for EN specifik station.
        Kaldes kun når station faktisk vælges af bruger.
        """
        if station.get('detailed_calculated', False):
            return station  # Allerede beregnet
        
        print(f"Calculating detailed surface waves for {station['network']}.{station['station']}")
        
        # Hent parametre
        distance_km = station['distance_km']
        eq_depth = earthquake.get('depth', 10.0)
        magnitude = earthquake.get('magnitude', 6.5)
        p_arrival = station.get('p_arrival')
        s_arrival = station.get('s_arrival')
        
        # BRUG AVANCERET OVERFLADEBØLGE BEREGNING - NU KUN FOR ÉN STATION
        surface_waves = self.calculate_surface_wave_velocities(
            distance_km=distance_km,
            depth_km=eq_depth,
            magnitude=magnitude,
            p_arrival_sec=p_arrival,
            s_arrival_sec=s_arrival
        )
        
        # Opdater station med detaljerede beregninger
        station.update({
            'love_arrival': surface_waves['love_arrival'],
            'rayleigh_arrival': surface_waves['rayleigh_arrival'],
            'surface_arrival': surface_waves['surface_arrival'],
            'love_velocity': surface_waves['love_velocity'],
            'rayleigh_velocity': surface_waves['rayleigh_velocity'],
            'surface_factors': surface_waves['calculation_factors'],
            'detailed_calculated': True
        })
        
        return station


    def get_station_with_detailed_calculations(self, station, earthquake):
        """
        Wrapper funktion der sikrer at stationen har detaljerede beregninger
        før den bruges til analyse
        """
        if not station.get('detailed_calculated', False):
            station = self.calculate_detailed_surface_waves_for_station(station, earthquake)
        
        return station
 
    def _process_inventory_to_stations(self, inventory, eq_lat, eq_lon, eq_depth, eq_time,
                                    min_distance_km, max_distance_km):
        """
        OPTIMERET Helper metode til at processere ObsPy inventory til station liste.
        
        VIGTIGE ÆNDRINGER:
        - Kun SIMPLE overfladebølge-beregninger under søgning
        - Avancerede beregninger kun når station vælges
        - Returnerer arrival times som SEKUNDER (float) ikke UTCDateTime!
        """
        stations = []
        
        # Network prioritering (lavere nummer = højere prioritet)
        network_scores = {
            'IU': 1, 'II': 2, 'G': 3, 'GE': 4, 'GT': 5,
            'IC': 6, 'CU': 7, 'US': 8, 'TA': 9, 'N4': 10
        }
        
        for network in inventory:
            for station in network:
                try:
                    # Basis distance og azimuth beregning
                    distance_deg, azimuth, _ = gps2dist_azimuth(
                        eq_lat, eq_lon, station.latitude, station.longitude
                    )
                    distance_km = distance_deg / 1000.0
                    distance_deg = distance_deg / 111195.0
                    
                    # Distance filter
                    if not (min_distance_km <= distance_km <= max_distance_km):
                        continue
                    
                    # Channel analyse
                    selected_channels = []
                    
                    for channel in station:
                        # Kun brede-bånd seismometre
                        if (channel.code.startswith(('BH', 'HH', 'SH', 'EH')) and 
                            channel.code[-1] in ['Z', 'N', 'E', '1', '2']):
                            selected_channels.append(channel)
                    
                    if not selected_channels:
                        continue
                    
                    # Channel prioritering
                    priority_order = ['BH', 'HH', 'SH', 'EH']
                    channel_priority = 99
                    
                    for i, prefix in enumerate(priority_order):
                        if any(ch.code.startswith(prefix) for ch in selected_channels):
                            channel_priority = i + 1
                            break
                    
                    # Sample rate analyse
                    rates = [ch.sample_rate for ch in selected_channels if ch.sample_rate]
                    typical_rate = max(rates) if rates else 20.0
                    
                    # Operational years
                    operational_years = 0
                    if station.start_date:
                        operational_years = eq_time.year - station.start_date.year
                    
                    # ✅ SIMPLE P og S arrival beregninger med TauP
                    try:
                        arrivals = self.taup_model.get_travel_times(
                            source_depth_in_km=eq_depth,
                            distance_in_degree=distance_deg,
                            phase_list=['P', 'S']
                        )
                        
                        p_arrival_seconds = None
                        s_arrival_seconds = None
                        
                        for arrival in arrivals:
                            if arrival.name == 'P' and p_arrival_seconds is None:
                                p_arrival_seconds = arrival.time
                            elif arrival.name == 'S' and s_arrival_seconds is None:
                                s_arrival_seconds = arrival.time
                        
                    except Exception:
                        # Fallback simple beregning
                        p_arrival_seconds = distance_km / 8.0 if distance_km > 0 else None
                        s_arrival_seconds = distance_km / 4.5 if distance_km > 0 else None
                    
                    # ✅ SIMPLE overfladebølge estimater (UDEN avancerede beregninger)
                    if distance_km > 0:
                        # Standard hastigheder - ingen komplekse faktorer!
                        simple_love_velocity = 4.2
                        simple_rayleigh_velocity = 3.7
                        
                        love_arrival_simple = distance_km / simple_love_velocity
                        rayleigh_arrival_simple = distance_km / simple_rayleigh_velocity
                        surface_arrival_simple = min(love_arrival_simple, rayleigh_arrival_simple)
                    else:
                        love_arrival_simple = 0
                        rayleigh_arrival_simple = 0
                        surface_arrival_simple = 0
                    
                    # ✅ Station info med SIMPLE beregninger
                    station_info = {
                        'network': network.code,
                        'station': station.code,
                        'latitude': round(station.latitude, 4),
                        'longitude': round(station.longitude, 4),
                        'elevation': round(station.elevation, 1) if station.elevation else 0,
                        
                        # Distance info
                        'distance_km': round(distance_km, 1),
                        'distance_deg': round(distance_deg, 2),
                        'azimuth': round(azimuth, 1),
                        
                        # SIMPLE arrival times som SEKUNDER (float)
                        'p_arrival': round(p_arrival_seconds, 3) if p_arrival_seconds else None,
                        's_arrival': round(s_arrival_seconds, 3) if s_arrival_seconds else None,
                        'love_arrival': round(love_arrival_simple, 1),
                        'rayleigh_arrival': round(rayleigh_arrival_simple, 1),
                        'surface_arrival': round(surface_arrival_simple, 1),
                        
                        # PLACEHOLDER for avancerede beregninger (beregnes ved behov)
                        'love_velocity': 4.2,  # Standard værdi
                        'rayleigh_velocity': 3.7,  # Standard værdi
                        'surface_factors': None,  # Beregnes kun når station vælges
                        'detailed_calculated': False,  # Flag for detaljeret beregning
                        
                        # ALLE ORIGINALE KVALITETSFELTER BEVARET
                        'channels': len(selected_channels),
                        'sample_rate': typical_rate,
                        'channel_codes': ','.join([ch.code for ch in selected_channels[:3]]),
                        'network_priority': network_scores.get(network.code, 99),
                        'channel_priority': channel_priority,
                        'operational_years': operational_years,
                        'data_verified': None  # Sættes under validering
                    }
                    
                    stations.append(station_info)
                    
                except Exception as e:
                    print(f"Error processing station {network.code}.{station.code}: {e}")
                    continue
        
        print(f"Processed {len(stations)} stations with SIMPLE calculations only")
        return stations


    def debug_surface_wave_calls(self):
        """
        Debug funktion til at spore hvornår surface wave beregninger kaldes
        """
        original_method = self.calculate_surface_wave_velocities
        
        def wrapped_method(*args, **kwargs):
            import traceback
            print(f"🔍 calculate_surface_wave_velocities called from:")
            # Vis de sidste 3 levels af call stack
            for line in traceback.format_stack()[-4:-1]:
                print(f"  {line.strip()}")
            return original_method(*args, **kwargs)
        
        self.calculate_surface_wave_velocities = wrapped_method
        print("✅ Surface wave debugging enabled")


    def clear_detailed_calculations_flag(self):
        """
        Rydder detailed_calculated flag fra alle cached stationer
        """
        if 'search_in_progress' in st.session_state:
            for cache_key, stations in st.session_state.search_in_progress.items():
                if isinstance(stations, list):
                    for station in stations:
                        if isinstance(station, dict) and 'detailed_calculated' in station:
                            station['detailed_calculated'] = False
            print("✅ Cleared detailed_calculated flags from cache")
   
    def _select_distributed_stations(self, stations, target_count):
        """
        SUPER OPTIMERET geografisk fordeling fra v1.7
        """
        print(f"\n=== FAST _select_distributed_stations ===")
        print(f"Input stations: {len(stations)}, Target: {target_count}")
        
        if len(stations) <= target_count:
            print(f"Not enough stations for selection, returning all {len(stations)}")
            return stations
        
        # HURTIG METODE for store datasets (>100 stationer)
        if len(stations) > 100:
            print("Using FAST algorithm for large dataset")
            
            # Dedupliker først
            seen = set()
            unique_stations = []
            for station in stations:
                station_key = (station['network'], station['station'])
                if station_key not in seen:
                    seen.add(station_key)
                    unique_stations.append(station)
            
            if len(unique_stations) <= target_count:
                return unique_stations
            
            # Sorter efter afstand
            sorted_stations = sorted(unique_stations, key=lambda x: x['distance_km'])
            
            # BINNING approach - meget hurtigere end bucket metode
            distances = np.array([s['distance_km'] for s in sorted_stations])
            
            # Opret bins
            bin_edges = np.linspace(distances.min(), distances.max(), target_count + 1)
            selected = []
            selected_indices = set()
            
            # Vælg én station fra hver bin
            for i in range(len(bin_edges) - 1):
                bin_start = bin_edges[i]
                bin_end = bin_edges[i + 1]
                bin_center = (bin_start + bin_end) / 2
                
                # Find stationer i denne bin
                available_stations = [
                    (j, s) for j, s in enumerate(sorted_stations)
                    if j not in selected_indices and 
                    bin_start <= s['distance_km'] <= bin_end
                ]
                
                if available_stations:
                    # Tag nærmeste til bin center
                    best_idx, best_station = min(
                        available_stations,
                        key=lambda x: abs(x[1]['distance_km'] - bin_center)
                    )
                    selected.append(best_station)
                    selected_indices.add(best_idx)
            
            # Fill up if needed
            if len(selected) < target_count:
                for j, station in enumerate(sorted_stations):
                    if j not in selected_indices and len(selected) < target_count:
                        selected.append(station)
                        selected_indices.add(j)
            
            print(f"FAST algorithm selected {len(selected)} stations")
            return selected[:target_count]
        
        else:
            # Original bucket method for mindre datasets
            print("Using ORIGINAL bucket algorithm")
            
            stations_sorted = sorted(stations, key=lambda x: x['distance_km'])
            
            # Opret afstandsbuckets
            min_dist = stations_sorted[0]['distance_km']
            max_dist = stations_sorted[-1]['distance_km']
            
            buckets = []
            bucket_size = (max_dist - min_dist) / target_count
            
            for i in range(target_count):
                bucket_min = min_dist + i * bucket_size
                bucket_max = min_dist + (i + 1) * bucket_size
                bucket_stations = [s for s in stations_sorted 
                                 if bucket_min <= s['distance_km'] < bucket_max]
                if bucket_stations:
                    buckets.append(bucket_stations)
            
            # Vælg bedste fra hver bucket
            selected = []
            for bucket in buckets:
                if bucket:
                    # Sorter efter kvalitet inden for bucket
                    bucket.sort(key=lambda x: (
                        x.get('network_priority', 99),
                        -x.get('sample_rate', 0),
                        x.get('channel_priority', 99)
                    ))
                    selected.append(bucket[0])
            
            # Fill up hvis nødvendigt
            remaining = [s for s in stations_sorted if s not in selected]
            while len(selected) < target_count and remaining:
                selected.append(remaining.pop(0))
            
            print(f"ORIGINAL algorithm selected {len(selected)} stations")
            return selected[:target_count]
    
    def _validate_stations_parallel(self, stations, eq_time, target_count, 
                                   progress_bar, status_text):
        """
        OPTIMERET parallel validering med tidlig stop fra v1.7
        Checker kun data tilgængelighed, IKKE response requirement!
        """
        validated = []
        verified_count = 0
        lock = threading.Lock()
        
        # Funktion til at validere en enkelt station
        def validate_single(station):
            try:
                # Super hurtig check - kun 30 sekunder data
                # VIGTIGT: Dette er KUN til at verificere at stationen har data
                # Den fulde download sker senere med hele tidsvinduet!
                start_time = eq_time
                end_time = eq_time + 30
                
                # Prøv kun HH eller BH kanaler først
                for channels in ["HH?", "BH?"]:
                    try:
                        # VIGTIGT: Dette er kun en TEST - ikke den faktiske data!
                        test_stream = self.client.get_waveforms(
                            network=station['network'],
                            station=station['station'],
                            location='*',
                            channel=channels,
                            starttime=start_time,
                            endtime=end_time
                        )
                        
                        if test_stream and len(test_stream) > 0:
                            station['data_verified'] = True
                            station['verified_channels'] = channels
                            return station
                    except:
                        continue
                
                # Ingen data fundet
                station['data_verified'] = False
                return station
                
            except Exception as e:
                station['data_verified'] = False
                station['error'] = str(e)
                return station
        
        # Parallel execution med early termination
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(validate_single, station): station 
                      for station in stations}
            
            for future in as_completed(futures):
                if verified_count >= target_count * 2:
                    # Har nok verificerede, stop
                    break
                
                try:
                    result = future.result(timeout=5)
                    
                    with lock:
                        validated.append(result)
                        if result.get('data_verified', False):
                            verified_count += 1
                        
                        # Update progress
                        progress = min(0.7 + (0.2 * len(validated) / len(stations)), 0.9)
                        progress_bar.progress(progress)
                        status_text.text(
                            f"✓ Verificeret {verified_count} af {len(validated)} stationer..."
                        )
                except:
                    pass
        
        # Sorter: verificerede først
        validated.sort(key=lambda x: (not x.get('data_verified', False), x['distance_km']))
        
        return validated
    
    def _fallback_station_list_optimized(self, earthquake, min_distance_km, max_distance_km, target_stations):
        """
        Fallback til kendte gode stationer hvis IRIS søgning fejler
        """
        eq_lat = earthquake.get('latitude', 0)
        eq_lon = earthquake.get('longitude', 0)
        eq_depth = earthquake.get('depth', 10)
        
        # Analyse-klar stationer fra Europa (tættere på Danmark)
        analysis_ready_stations = [
            {'net': 'IU', 'sta': 'KEV', 'lat': 69.76, 'lon': 27.01},      # Finland
            {'net': 'II', 'sta': 'BFO', 'lat': 48.33, 'lon': 8.33},       # Tyskland  
            {'net': 'GE', 'sta': 'STU', 'lat': 48.77, 'lon': 9.19},       # Tyskland
            {'net': 'DK', 'sta': 'BSD', 'lat': 55.11, 'lon': 14.91},      # Bornholm
            {'net': 'DK', 'sta': 'COP', 'lat': 55.68, 'lon': 12.43},      # København
            {'net': 'NS', 'sta': 'BSEG', 'lat': 62.20, 'lon': 5.22},      # Norge
            {'net': 'UP', 'sta': 'UDD', 'lat': 64.51, 'lon': 21.04},      # Sverige
        ]
        
        stations = []
        for sta_data in analysis_ready_stations:
            try:
                # Beregn afstand til jordskælv
                distance_m, azimuth, _ = gps2dist_azimuth(
                    eq_lat, eq_lon, sta_data['lat'], sta_data['lon']
                )
                distance_km = distance_m / 1000.0
                distance_deg = kilometers2degrees(distance_km)
                
                # Kontroller om i ønsket afstands range
                if min_distance_km <= distance_km <= max_distance_km:
                    # Beregn ankomsttider som SEKUNDER
                    love_arrival = distance_km / 4.5      # ~4.5 km/s for Love bølger
                    rayleigh_arrival = distance_km / 3.5  # ~3.5 km/s for Rayleigh bølger
                    surface_arrival = rayleigh_arrival  # Default til Rayleigh

                    
                    # Opret station dictionary
                    station = {
                        'network': sta_data['net'],
                        'station': sta_data['sta'],
                        'latitude': sta_data['lat'],
                        'longitude': sta_data['lon'],
                        'distance_deg': round(distance_deg, 2),
                        'distance_km': round(distance_km, 1),
                        'azimuth': round(azimuth, 1),
                        'p_arrival': round(p_arrival, 3),
                        's_arrival': round(s_arrival, 3),
                        'love_arrival': round(love_arrival, 3),
                        'rayleigh_arrival': round(rayleigh_arrival, 3),
                        'surface_arrival': round(surface_arrival, 3),
                        'data_source': 'ANALYSIS_READY_FALLBACK',
                        'data_verified': None
                    }
                    stations.append(station)
            except:
                continue
        
        # Sortér efter afstand og returner
        stations.sort(key=lambda x: x['distance_km'])
        return stations[:target_stations]
    
    # ========================================
    # WAVEFORM DOWNLOAD - PRAGMATISK APPROACH
    # ========================================
    def download_waveform_data(self, earthquake, station):
        """
        FORBEDRET version - BEVARER din eksisterende hastigheds-optimering
        Tilføjer kun auto-fallback marking - INGEN nye langsomme processer
        """
        print(f"🌊 FORBEDRET DOWNLOAD: Starting for {station['network']}.{station['station']}")
        
        try:
            # BEVAR din eksisterende earthquake data processing
            eq_time = ensure_utc_datetime(earthquake['time'])  # Brug din eksisterende funktion
            if not eq_time:
                print(f"❌ Invalid earthquake time")
                return None
            
            # BEVAR din eksisterende tidsvindue optimering
            start_time = eq_time - 180  # 3 minutter før (din eksisterende optimering)
            end_time = eq_time + 1800   # 30 minutter efter (din eksisterende optimering)
            
            print(f"🌊 TIME WINDOW: {start_time} to {end_time}")
            
            # BEVAR din eksisterende IRIS connection
            if not hasattr(self, 'client') or self.client is None:
                self.connect_to_iris()
            
            # BEVAR din eksisterende OPTIMERET channel request
            priority_channels = [
                f"{station['network']}.{station['station']}.*.BH?",
                f"{station['network']}.{station['station']}.*.HH?",
                f"{station['network']}.{station['station']}.*.SH?"
            ]
            
            stream = None
            
            # BEVAR din eksisterende channel priority loop
            for channel_pattern in priority_channels:
                try:
                    print(f"🌊 TRYING: {channel_pattern}")
                    
                    stream = self.client.get_waveforms(
                        network=station['network'],
                        station=station['station'],
                        location="*",
                        channel=channel_pattern.split('.')[-1],
                        starttime=start_time,
                        endtime=end_time,
                        attach_response=True
                    )
                    
                    if stream and len(stream) >= 2:  # Mindst 2 komponenter
                        print(f"✅ SUCCESS: Got {len(stream)} traces with {channel_pattern}")
                        break
                        
                except Exception as e:
                    print(f"⚠️ FAILED: {channel_pattern} - {e}")
                    continue
            
            # BEVAR din eksisterende fallback logic
            if not stream:
                print(f"🔄 FALLBACK: Trying broader search...")
                
                try:
                    stream = self.client.get_waveforms(
                        network=station['network'],
                        station=station['station'],
                        location="*",
                        channel="*",  # Alle kanaler
                        starttime=start_time,
                        endtime=end_time,
                        attach_response=True
                    )
                    
                    if stream and len(stream) >= 1:
                        print(f"✅ FALLBACK SUCCESS: Got {len(stream)} traces with broad search")
                    else:
                        print(f"❌ FALLBACK FAILED: Still no data")
                        
                except Exception as e:
                    print(f"❌ FALLBACK ERROR: {e}")
            
            if not stream:
                print(f"❌ NO DATA: Could not get waveforms after all attempts")
                
                # NY: Trigger automatic fallback - INGEN performance impact
                cache_key = f"{earthquake.get('time')}_{station['network']}_{station['station']}"
                st.session_state.download_failed = cache_key
                
                return None
            
            # BEVAR din eksisterende processing - INGEN ændringer
            waveform_data = self._process_real_waveform_FIXED(
                stream, earthquake, station, start_time, end_time
            )
            
            if waveform_data:
                print(f"✅ PROCESSED: Waveform data ready")
                return waveform_data
            else:
                print(f"❌ PROCESSING FAILED")
                
                # NY: Mark som failed - INGEN performance impact
                cache_key = f"{earthquake.get('time')}_{station['network']}_{station['station']}"
                st.session_state.download_failed = cache_key
                
                return None
                
        except Exception as e:
            print(f"❌ DOWNLOAD ERROR: {e}")
            
            # NY: Mark som failed - INGEN performance impact
            cache_key = f"{earthquake.get('time')}_{station['network']}_{station['station']}"
            st.session_state.download_failed = cache_key
            
            return None   

    def _process_real_waveform_FIXED(self, stream, earthquake, station, start_time, end_time):
        """
        Process waveforms med v1.7's pragmatiske approach.
        FIXED: Eliminerer duplicate komponenter efter merge.
        OPDATERET: INGEN downsampling - gem alt i fuld opløsning.
        """
        try:
            print(f"DEBUG: Processing {len(stream)} traces")
            
            # Kopier stream for at undgå at ændre original
            work_stream = stream.copy()
            
            # Pre-process: Merge
            print("DEBUG: Merging stream...")
            work_stream.merge(method=1, fill_value=0)
            print(f"DEBUG: After merge: {len(work_stream)} traces")
            
            # VIGTIG: Check for og fjern duplicates efter merge
            unique_channels = {}
            for tr in work_stream:
                channel_id = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}.{tr.stats.channel}"
                if channel_id not in unique_channels:
                    unique_channels[channel_id] = tr
                else:
                    print(f"DEBUG: Removing duplicate channel: {channel_id}")
            
            # Opret ny stream med kun unique channels
            work_stream = Stream()
            for tr in unique_channels.values():
                work_stream.append(tr)
            
            print(f"DEBUG: After deduplication: {len(work_stream)} traces")
            
            # Hent inventory for response removal
            inventory = None
            try:
                print("DEBUG: Fetching station inventory...")
                inventory = self.client.get_stations(
                    network=station['network'],
                    station=station['station'],
                    starttime=start_time,
                    endtime=end_time,
                    level="response"
                )
                print("DEBUG: Inventory fetched successfully")
            except Exception as e:
                print(f"DEBUG: Could not fetch inventory: {e}")
                inventory = None
            
            # Gem raw data FØRST (før response removal)
            raw_data = {}
            for tr in work_stream:
                channel = tr.stats.channel
                component = channel[-1]
                
                # Map til standard komponenter
                if component == 'Z' or component == '3':
                    raw_data['vertical'] = tr.data.copy()
                elif component == 'N' or component == '1':
                    raw_data['north'] = tr.data.copy()
                elif component == 'E' or component == '2':
                    raw_data['east'] = tr.data.copy()
            
            # Response removal (hvis muligt)
            units = 'counts'
            if inventory:
                try:
                    print("DEBUG: Removing instrument response...")
                    # Pre-filter design baseret på sampling rate
                    sample_rate = work_stream[0].stats.sampling_rate
                    nyquist = sample_rate / 2.0
                    pre_filt = [0.005, 0.01, nyquist * 0.8, nyquist * 0.9]
                    
                    work_stream.remove_response(
                        inventory=inventory,
                        output='DISP',
                        pre_filt=pre_filt,
                        water_level=60,
                        plot=False
                    )
                    
                    # Konverter fra meter til mm
                    for tr in work_stream:
                        tr.data = tr.data * 1000.0
                    
                    units = 'mm'
                    print("DEBUG: Response removal successful")
                except Exception as e:
                    print(f"DEBUG: Response removal failed: {e}")
                    units = 'counts'
            
            # Byg output struktur med FULD opløsning
            waveform_data = {}
            
            # Process hver trace
            for tr in work_stream:
                channel = tr.stats.channel
                component = channel[-1]
                
                # Gem fuld opløsning waveform data
                waveform_data[f'waveform_{component}'] = tr.data
                waveform_data[f'sampling_rate_{component}'] = tr.stats.sampling_rate
                waveform_data[f'npts_{component}'] = tr.stats.npts
                
                # Generer time array (relativ til jordskælv)
                eq_time = ensure_utc_datetime(earthquake.get('time'))
                trace_start = tr.stats.starttime
                time_offset = float(trace_start - eq_time)
                times = np.arange(tr.stats.npts) / tr.stats.sampling_rate + time_offset
                waveform_data[f'time_{component}'] = times
            
            # Tilføj earthquake time
            eq_time = ensure_utc_datetime(earthquake.get('time'))
            if eq_time:
                waveform_data['earthquake_time'] = eq_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Metadata
            waveform_data['units'] = units
            waveform_data['start_time_offset'] = float(start_time - eq_time)
            
            # Byg displacement_data struktur
            displacement_data = {}
            component_mapping = {
                'Z': 'vertical', 
                'N': 'north', 
                'E': 'east',
                '1': 'north',
                '2': 'east',
                '3': 'vertical'
            }
            
            mapped_components = set()
            for comp, name in component_mapping.items():
                if f'waveform_{comp}' in waveform_data and name not in mapped_components:
                    displacement_data[name] = waveform_data[f'waveform_{comp}']
                    mapped_components.add(name)
            
            if displacement_data:
                waveform_data['displacement_data'] = displacement_data
            
            # Tilføj raw_data
            waveform_data['raw_data'] = raw_data
            
            # Find sampling rate (højeste)
            sampling_rates = [v for k, v in waveform_data.items() if k.startswith('sampling_rate_')]
            if sampling_rates:
                waveform_data['sampling_rate'] = max(sampling_rates)
            else:
                waveform_data['sampling_rate'] = 40.0  # fallback
            
            # Tilføj generel time array
            if 'time_Z' in waveform_data:
                waveform_data['time'] = waveform_data['time_Z']
            elif any(k.startswith('time_') for k in waveform_data.keys()):
                first_time_key = next(k for k in waveform_data.keys() if k.startswith('time_'))
                waveform_data['time'] = waveform_data[first_time_key]
            
            # Available components
            available_components = []
            for comp in ['Z', 'N', 'E', '1', '2', '3']:
                if f'waveform_{comp}' in waveform_data:
                    available_components.append(comp)
            waveform_data['available_components'] = available_components
            
            # Data source
            waveform_data['data_source'] = 'IRIS'
            
            # Summary info
            print(f"DEBUG: Final sampling rate: {waveform_data.get('sampling_rate')} Hz")
            print(f"DEBUG: Data length: {len(waveform_data.get('time', []))} samples")
            print(f"DEBUG: Units: {units}")
            
            return waveform_data
            
        except Exception as e:
            print(f"ERROR in _process_real_waveform_FIXED: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def validate_and_correct_timing(self, waveform_data: Dict[str, Any], 
                                   earthquake: Dict[str, Any], 
                                   station: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validerer og korrigerer timing baseret på P-wave detection.
        Returnerer altid data - fejler aldrig!
        """
        if not self.processor:
            return waveform_data
        
        try:
            # Find Z-komponent
            z_data = waveform_data.get('waveform_Z')
            z_time = waveform_data.get('time_Z')
            
            if z_data is None or z_time is None:
                # Prøv andre komponenter
                for comp in ['N', 'E', '1', '2']:
                    if f'waveform_{comp}' in waveform_data:
                        z_data = waveform_data[f'waveform_{comp}']
                        z_time = waveform_data[f'time_{comp}']
                        break
            
            if z_data is None:
                return waveform_data
            
            # Teoretisk P-wave tid
            p_theoretical = station.get('p_arrival', 0)
            if not p_theoretical:
                return waveform_data
            
            # Detect P-wave
            detected_p, confidence, _ = self.processor.detect_p_wave_arrival(
                z_data, z_time, p_theoretical
            )
            
            if detected_p and confidence > 0.7:
                # Beregn korrektion
                time_correction = detected_p - p_theoretical
                
                if abs(time_correction) < 10.0:  # Max 10 sekunder korrektion
                    # Anvend korrektion
                    for key in waveform_data:
                        if key.startswith('time_'):
                            waveform_data[key] = waveform_data[key] - time_correction
                    
                    waveform_data['timing_corrected'] = True
                    waveform_data['timing_correction'] = time_correction
                    
                    st.info(f"✓ Timing korrigeret med {time_correction:.1f} sekunder")
            
            return waveform_data
            
        except Exception as e:
            print(f"Timing correction error: {e}")
            return waveform_data

#=================================
# L og R-bølgehastigheder
#================================
    def calculate_surface_wave_velocities(self, distance_km, depth_km, magnitude, 
                                        p_arrival_sec=None, s_arrival_sec=None):
        """
        Beregner realistiske Love og Rayleigh bølgehastigheder baseret på:
        - Jordskælvets dybde
        - Magnitude  
        - Observerede P og S ankomsttider (valgfri)
        
        Returns:
            dict: Hastigheder og ankomsttider for overfladebølger
        """
        
        # Basis hastigheder (km/s) - globale gennemsnit
        base_love_velocity = 4.5
        base_rayleigh_velocity = 3.5
        
        # 1. DYBDE EFFEKT - dybe jordskælv genererer svagere overfladebølger
        if depth_km < 20:
            depth_factor = 1.0  # Optimal dybde for overfladebølger
        elif depth_km < 35:
            depth_factor = 0.98
        elif depth_km < 70:
            depth_factor = 0.92
        elif depth_km < 150:
            depth_factor = 0.80
        elif depth_km < 300:
            depth_factor = 0.65
        else:
            depth_factor = 0.50  # Meget dybe jordskælv har svage overfladebølger
        
        # 2. AFSTANDS EFFEKT (Dispersion)
        # Overfladebølger disperserer - længere perioder rejser hurtigere
        if distance_km < 500:
            distance_factor = 0.92  # Kort afstand - domineret af korte perioder
        elif distance_km < 1000:
            distance_factor = 0.95
        elif distance_km < 2000:
            distance_factor = 0.98
        elif distance_km < 4000:
            distance_factor = 1.0   # Optimal afstand
        elif distance_km < 6000:
            distance_factor = 1.02
        elif distance_km < 10000:
            distance_factor = 1.04
        else:
            distance_factor = 1.06  # Lang afstand - domineret af lange perioder
        
        # 3. MAGNITUDE EFFEKT
        # Større jordskælv exciterer længere perioder = højere gruppehastighed
        if magnitude < 5.0:
            magnitude_factor = 0.95  # Små jordskælv - korte perioder
        elif magnitude < 5.5:
            magnitude_factor = 0.97
        elif magnitude < 6.0:
            magnitude_factor = 0.99
        elif magnitude < 6.5:
            magnitude_factor = 1.0   # Reference magnitude
        elif magnitude < 7.0:
            magnitude_factor = 1.02
        elif magnitude < 7.5:
            magnitude_factor = 1.04
        elif magnitude < 8.0:
            magnitude_factor = 1.06
        else:
            magnitude_factor = 1.08  # Store jordskælv - lange perioder
        
        # 4. SKORPESTRUKTUR (hvis P og S tider er tilgængelige)
        structure_factor = 1.0
        vp_vs_ratio_info = None
        
        if p_arrival_sec and s_arrival_sec and p_arrival_sec > 0:
            # Beregn Vp/Vs ratio fra ankomsttider
            # Ts - Tp = afstand * (1/Vs - 1/Vp)
            # Hvis Vp/Vs = k, så Ts - Tp = afstand/Vp * (k - 1)
            # Ts/Tp ≈ Vp/Vs for samme ray path
            
            ts_tp_ratio = s_arrival_sec / p_arrival_sec
            estimated_vp_vs = ts_tp_ratio  # Approksimation
            
            vp_vs_ratio_info = round(estimated_vp_vs, 2)
            
            if estimated_vp_vs > 1.80:
                structure_factor = 0.93  # Høj Vp/Vs = sedimenter/vand
                structure_type = "Sedimentær"
            elif estimated_vp_vs > 1.75:
                structure_factor = 0.97  # Normal continental crust
                structure_type = "Normal skorpe"
            elif estimated_vp_vs > 1.70:
                structure_factor = 1.0
                structure_type = "Gennemsnitlig"
            else:
                structure_factor = 1.05  # Lav Vp/Vs = krystallin skorpe
                structure_type = "Krystallin"
        else:
            structure_type = "Ukendt"
        
        # Beregn finale hastigheder
        love_velocity = base_love_velocity * depth_factor * distance_factor * magnitude_factor * structure_factor
        rayleigh_velocity = base_rayleigh_velocity * depth_factor * distance_factor * magnitude_factor * structure_factor
        
        # Love bølger er typisk 10-15% hurtigere end Rayleigh
        love_velocity = rayleigh_velocity * 1.12
        
        # Begræns til realistiske værdier
        love_velocity = max(3.8, min(5.2, love_velocity))
        rayleigh_velocity = max(3.0, min(4.5, rayleigh_velocity))
        
        # Beregn ankomsttider i sekunder
        love_arrival = distance_km / love_velocity
        rayleigh_arrival = distance_km / rayleigh_velocity
        
        # Debug information
        print(f"Surface wave calculation for M{magnitude} at {distance_km:.0f}km, depth {depth_km}km:")
        print(f"  Factors: depth={depth_factor:.2f}, dist={distance_factor:.2f}, mag={magnitude_factor:.2f}, struct={structure_factor:.2f}")
        print(f"  Velocities: Love={love_velocity:.2f} km/s, Rayleigh={rayleigh_velocity:.2f} km/s")
        
        return {
            'love_velocity': round(love_velocity, 2),
            'rayleigh_velocity': round(rayleigh_velocity, 2),
            'love_arrival': round(love_arrival, 1),
            'rayleigh_arrival': round(rayleigh_arrival, 1),
            'surface_arrival': round(rayleigh_arrival, 1),  # Default til Rayleigh
            # Metadata for visning i teori sektionen
            'calculation_factors': {
                'depth_factor': round(depth_factor, 3),
                'distance_factor': round(distance_factor, 3),
                'magnitude_factor': round(magnitude_factor, 3),
                'structure_factor': round(structure_factor, 3),
                'vp_vs_ratio': vp_vs_ratio_info,
                'structure_type': structure_type
            }
        }

    
    # ========================================
    # EXCEL EXPORT
    # ========================================
    def export_to_excel(self, earthquake, station, waveform_data, ms_magnitude, ms_explanation, export_options=None):
            """
            Eksporterer komplet analyse til Excel format med metadata og tidsserier.
            
            Args:
                earthquake (dict): Jordskælv metadata
                station (dict): Station metadata
                waveform_data (dict): Processeret waveform data
                ms_magnitude (float): Beregnet Ms magnitude
                ms_explanation (str or dict): Ms beregnings forklaring
                export_options (dict): Dictionary med export valg
                    
            Returns:
                bytes or None: Excel fil som byte array eller None ved fejl
            """
            try:
                output = BytesIO()
                workbook = xlsxwriter.Workbook(output, {'in_memory': True})
                
                # Metadata sheet med formatering
                metadata_sheet = workbook.add_worksheet('Metadata')
                
                # Formatering definitioner
                header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3'})
                
                # Headers
                metadata_sheet.write('A1', 'Parameter', header_format)
                metadata_sheet.write('B1', 'Value', header_format)
                
                # Jordskælv metadata
                row = 1
                metadata_sheet.write(row, 0, 'Earthquake Magnitude')
                metadata_sheet.write(row, 1, earthquake['magnitude'])
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Latitude')
                metadata_sheet.write(row, 1, earthquake.get('latitude', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Longitude')
                metadata_sheet.write(row, 1, earthquake.get('longitude', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Depth (km)')
                metadata_sheet.write(row, 1, earthquake.get('depth', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Time')
                time_str = earthquake.get('time', 'N/A')
                if hasattr(time_str, 'isoformat'):
                    time_str = time_str.isoformat()
                metadata_sheet.write(row, 1, str(time_str))
                row += 1
                
                # Station metadata
                metadata_sheet.write(row, 0, 'Station Network')
                metadata_sheet.write(row, 1, station.get('network', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Station Code')
                metadata_sheet.write(row, 1, station.get('station', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Station Location')
                metadata_sheet.write(row, 1, f"Lat: {station.get('latitude', 'N/A')}, Lon: {station.get('longitude', 'N/A')}")
                row += 1
                
                metadata_sheet.write(row, 0, 'Distance (km)')
                metadata_sheet.write(row, 1, station.get('distance_km', 'N/A'))
                row += 1
                
                # Ms magnitude (hvis tilgængelig)
                if ms_magnitude is not None:
                    metadata_sheet.write(row, 0, 'Calculated Ms Magnitude')
                    metadata_sheet.write(row, 1, f"{ms_magnitude:.2f}")
                    row += 1
                
                # Time series data sheet
                timeseries_sheet = workbook.add_worksheet('Time_Series_Data')
                
                # Bestem hvilke data der skal eksporteres
                if export_options is None:
                    export_options = {
                        'raw_data': False,
                        'unfiltered': True,
                        'broadband': False,
                        'surface': False,
                        'p_waves': False,
                        's_waves': False
                    }
                
                # Headers og data kolonner
                headers = ['Time (s)']
                data_columns = []
                
                # Check hvilke komponenter der er tilgængelige
                components = ['north', 'east', 'vertical']
                
                # Tilføj rådata kolonner hvis valgt
                if export_options.get('raw_data') and 'raw_data' in waveform_data:
                    for comp in components:
                        if comp in waveform_data['raw_data']:
                            headers.append(f'{comp.capitalize()}_Raw (counts)')
                            data_columns.append(('raw_data', comp))
                
                # Tilføj displacement data hvis valgt
                if export_options.get('unfiltered') and 'displacement_data' in waveform_data:
                    for comp in components:
                        if comp in waveform_data['displacement_data']:
                            headers.append(f'{comp.capitalize()} (mm)')
                            data_columns.append(('displacement_data', comp))
                
                # Tilføj filtrerede data hvis tilgængelige
                filter_mapping = {
                    'broadband': 'Broadband',
                    'surface': 'Surface',
                    'p_waves': 'P-wave',
                    's_waves': 'S-wave'
                }
                
                for filter_key, filter_name in filter_mapping.items():
                    if export_options.get(filter_key) and 'filtered_datasets' in waveform_data:
                        if filter_key in waveform_data['filtered_datasets']:
                            for comp in components:
                                if comp in waveform_data['filtered_datasets'][filter_key]:
                                    headers.append(f'{comp.capitalize()}_{filter_name} (mm)')
                                    data_columns.append(('filtered_datasets', filter_key, comp))
                
                # Skriv headers
                for col, header in enumerate(headers):
                    timeseries_sheet.write(0, col, header, header_format)
                
                # Downsampling hvis nødvendigt
                max_samples = export_options.get('max_samples', 7200)
                time_array = waveform_data.get('time', [])
                
                if len(time_array) > max_samples and max_samples > 0:
                    # Beregn downsampling faktor
                    factor = len(time_array) // max_samples
                    indices = list(range(0, len(time_array), factor))[:max_samples]
                else:
                    indices = list(range(len(time_array)))
                
                # Skriv data
                for row_idx, idx in enumerate(indices):
                    row = row_idx + 1
                    
                    # Tid kolonne
                    if idx < len(time_array):
                        timeseries_sheet.write(row, 0, float(time_array[idx]))
                    
                    # Data kolonner
                    col = 1
                    for data_spec in data_columns:
                        try:
                            if len(data_spec) == 2:  # raw_data eller displacement_data
                                data_type, component = data_spec
                                if data_type in waveform_data and component in waveform_data[data_type]:
                                    data_array = waveform_data[data_type][component]
                                    if idx < len(data_array):
                                        value = float(data_array[idx])
                                    else:
                                        value = 0.0
                                else:
                                    value = 0.0
                            elif len(data_spec) == 3:  # filtered_datasets
                                data_type, filter_key, component = data_spec
                                if (data_type in waveform_data and 
                                    filter_key in waveform_data[data_type] and 
                                    component in waveform_data[data_type][filter_key]):
                                    data_array = waveform_data[data_type][filter_key][component]
                                    if idx < len(data_array):
                                        value = float(data_array[idx])
                                    else:
                                        value = 0.0
                                else:
                                    value = 0.0
                            else:
                                value = 0.0
                                
                            timeseries_sheet.write(row, col, value)
                        except (IndexError, ValueError, TypeError, KeyError):
                            timeseries_sheet.write(row, col, 0.0)
                        col += 1
                
                # Ms magnitude forklaring sheet (hvis tilgængelig)
                if ms_explanation:
                    explanation_sheet = workbook.add_worksheet('Ms_Calculation')
                    
                    # Håndter både string og dict format
                    if isinstance(ms_explanation, dict):
                        # Hvis det er en dict, konverter til string format
                        explanation_text = "Ms Magnitude Calculation Details\n\n"
                        for key, value in ms_explanation.items():
                            explanation_text += f"{key}: {value}\n"
                        explanation_lines = explanation_text.split('\n')
                    elif isinstance(ms_explanation, str):
                        # Split explanation i linjer
                        explanation_lines = ms_explanation.split('\n')
                    else:
                        # Fallback hvis det er noget andet
                        explanation_lines = [str(ms_explanation)]
                    
                    # Skriv linjer til sheet
                    for i, line in enumerate(explanation_lines):
                        if line.strip():  # Skip tomme linjer
                            # Fjern markdown formatering for Excel
                            clean_line = line.replace('**', '').replace('*', '').replace('***', '')
                            explanation_sheet.write(i, 0, clean_line)
                            
                # Wave Type Analysis sheet (hvis tilgængelig)
                if 'wave_analysis' in waveform_data:
                    wave_sheet = workbook.add_worksheet('Wave_Type_Analysis')
                    
                    # Headers
                    wave_sheet.write(0, 0, 'Parameter', header_format)
                    wave_sheet.write(0, 1, 'Value', header_format)
                    
                    wave_analysis = waveform_data['wave_analysis']
                    row = 1
                    
                    # Dominant type
                    wave_sheet.write(row, 0, 'Dominant Wave Type')
                    wave_sheet.write(row, 1, wave_analysis.get('dominant_type', 'Unknown'))
                    row += 1
                    
                    wave_sheet.write(row, 0, 'Confidence')
                    wave_sheet.write(row, 1, f"{wave_analysis.get('confidence', 0):.0%}")
                    row += 1
                    
                    wave_sheet.write(row, 0, 'Love/Rayleigh Ratio')
                    wave_sheet.write(row, 1, wave_analysis.get('love_rayleigh_ratio', 'N/A'))
                    row += 1
                    
                    wave_sheet.write(row, 0, 'Interpretation')
                    wave_sheet.write(row, 1, wave_analysis.get('interpretation', ''))
                    row += 1
                    
                    # Component energies
                    row += 1
                    wave_sheet.write(row, 0, 'Component Energies', header_format)
                    row += 1
                    
                    energies = wave_analysis.get('component_energy', {})
                    for comp, energy in energies.items():
                        wave_sheet.write(row, 0, f'{comp.capitalize()} Energy')
                        wave_sheet.write(row, 1, energy)
                        row += 1
                    
                    # RMS amplitudes
                    row += 1
                    wave_sheet.write(row, 0, 'RMS Amplitudes (mm)', header_format)
                    row += 1
                    
                    rms = wave_analysis.get('rms_amplitudes', {})
                    for comp, amp in rms.items():
                        wave_sheet.write(row, 0, f'{comp.capitalize()} RMS')
                        wave_sheet.write(row, 1, amp)
                        row += 1
                    
                    # Formatering
                    wave_sheet.set_column('A:A', 25)
                    wave_sheet.set_column('B:B', 20)
                # Formatering af kolonner
                metadata_sheet.set_column('A:A', 35)
                metadata_sheet.set_column('B:B', 50)
                timeseries_sheet.set_column('A:A', 12)  # Time kolonne
                
                # Sæt kolonnebredder for data kolonner
                num_data_cols = len(headers) - 1
                if num_data_cols > 0:
                    col_width = max(12, min(20, 200 // num_data_cols))
                    timeseries_sheet.set_column(1, num_data_cols, col_width)
                
                workbook.close()
                output.seek(0)
                
                return output.getvalue()
                
            except Exception as e:
                print(f"❌ Excel export error: {e}")
                import traceback
                traceback.print_exc()
                return None

    
    # ========================================
    # HELPER METHODS
    # ========================================
    
    def _check_cache(self, cache_type, key, max_age_hours=24):
        """Check cache med TTL"""
        cache = st.session_state.get(cache_type, {})
        if key in cache:
            data, timestamp = cache[key]
            age = (datetime.now() - timestamp).total_seconds() / 3600
            if age < max_age_hours:
                return data
        return None
    
    def _update_cache(self, cache_type, key, data):
        """Update cache med timestamp"""
        if cache_type not in st.session_state:
            st.session_state[cache_type] = {}
        st.session_state[cache_type][key] = (data, datetime.now())
        
        # Cleanup gamle entries
        self._clean_cache(cache_type)
    
    def _clean_cache(self, cache_type, max_entries=50):
        """Fjern gamle cache entries"""
        cache = st.session_state.get(cache_type, {})
        if len(cache) > max_entries:
            # Sorter efter timestamp og behold nyeste
            sorted_items = sorted(cache.items(), key=lambda x: x[1][1], reverse=True)
            st.session_state[cache_type] = dict(sorted_items[:max_entries])
    
    def _clean_memory(self):
        """Eksplicit memory cleanup"""
        gc.collect()
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    def get_earthquake_details(self, event_id):
        """Hent detaljer for specifikt jordskælv"""
        try:
            catalog = self.client.get_events(eventid=event_id)
            if catalog and len(catalog) > 0:
                return self._process_catalog([catalog[0]])[0]
        except:
            pass
        return None
    
    def get_earthquakes_by_region(self, region_bounds, **kwargs):
        """Hent jordskælv inden for geografisk område"""
        try:
            minlat, maxlat, minlon, maxlon = region_bounds
            
            catalog = self.client.get_events(
                minlatitude=minlat,
                maxlatitude=maxlat,
                minlongitude=minlon,
                maxlongitude=maxlon,
                **kwargs
            )
            
            return self._process_catalog(catalog)
        except Exception as e:
            st.error(f"Region søgning fejlede: {str(e)}")
            return []
    
    def clear_all_cache(self):
        """Rydder al cache"""
        cache_types = ['earthquake_cache', 'station_cache', 'waveform_cache', 'inventory_cache']
        for cache_type in cache_types:
            if cache_type in st.session_state:
                del st.session_state[cache_type]
        print("All cache cleared")
        gc.collect()
    
    def get_cache_stats(self):
        """Cache statistik"""
        stats = {}
        cache_types = ['earthquake_cache', 'station_cache', 'waveform_cache', 'inventory_cache']
        for cache_type in cache_types:
            stats[cache_type] = len(st.session_state.get(cache_type, {}))
        return stats
    
    # ========================================
    # ALIAS METHODS (for backward compatibility)
    # ========================================
    
    def search_earthquakes(self, **kwargs):
        """Alias for fetch_latest_earthquakes"""
        return self.fetch_latest_earthquakes(**kwargs)
    
    def find_stations_for_earthquake(self, earthquake, **kwargs):
        """Alias for search_stations"""
        return self.search_stations(earthquake, **kwargs)
    
    def download_waveforms(self, earthquake, station):
        """Alias for download_waveform_data"""
        return self.download_waveform_data(earthquake, station)