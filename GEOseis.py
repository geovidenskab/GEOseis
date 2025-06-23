# GEOseis.py v. 1.0
"""
Streamlined Professional Seismic Analysis Platform
====================================================================================

En avanceret seismologisk analyseplatform til realtids jordskælvsanalyse med:
- IRIS FDSN integration til data hentning
- Professionel signalprocessering med ObsPy
- Ms magnitude beregning efter IASPEI standarder
- Interaktive kort og visualiseringer
- Excel eksport til videre analyse

Udviklet af: Philip Kruse Jakobsen, Silkeborg Gymnasium
Version: 1.0
Dato: Juni 2025

Hovedklasser:
- EnhancedSeismicProcessor: Avanceret signalprocessering og magnitude beregning
- StreamlinedDataManager: IRIS data management og station søgning
- StreamlinedSeismicApp: Streamlit web interface

Krav:
- Python 3.8+
- ObsPy for seismologiske funktioner
- Streamlit til web interface
- Plotly til interaktive grafer
- Folium til kort visualisering
"""

import streamlit as st

st.cache_data.clear()
st.cache_resource.clear()


# Konfiguration af Streamlit applikation - skal være første Streamlit kommando
st.set_page_config(
    page_title="GEOseis - seismisk analyse med Excel-export til undervisningen",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Standard Python biblioteker
import pandas as pd
import numpy as np
import plotly.graph_objects as go
#import plotly.express as px
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
#import json
#import time
import traceback
#from scipy import signal
from scipy.signal import butter, filtfilt, medfilt
from scipy.fft import fft, fftfreq
from io import BytesIO
import xlsxwriter
import warnings

# ObsPy imports - kritiske for seismologisk funktionalitet
OBSPY_AVAILABLE = False
ADVANCED_FEATURES = False

try:
    import obspy
    from obspy.clients.fdsn import Client
    from obspy import UTCDateTime
    from obspy.geodetics import locations2degrees, gps2dist_azimuth
    from obspy.taup import TauPyModel
    from obspy.signal import filter
    OBSPY_AVAILABLE = True
    ADVANCED_FEATURES = True
except ImportError as e:
    st.error(f"❌ ObsPy required for this application: {e}")
    st.stop()


class EnhancedSeismicProcessor:
    """
    Avanceret seismisk dataprocessering med fokus på professional analyse.
    
    Denne klasse håndterer alle aspekter af seismisk signalprocessering:
    - Butterworth filtrering med automatisk frekvens validering
    - Spike detektion og fjernelse med robust statistik
    - Ms magnitude beregning efter IASPEI 2013 standarder
    - FFT spektral analyse af overfladebølger
    - P-bølge STA/LTA detektion
    - SNR beregning og datakvalitetsvurdering
    - TauP rejsetids modellering
    
    Attributes:
        taup_model: TauPyModel objekt til rejsetidsberegning (iasp91)
        filter_bands: Dictionary med prædefinerede filterbånd
        filter_order: Butterworth filter orden (default: 4)
        spike_threshold: Z-score grænse for spike detektion (default: 5.0)
    
    Example:
        processor = EnhancedSeismicProcessor()
        filtered_data = processor.apply_bandpass_filter(data, 100, 1.0, 10.0)
        ms_mag, explanation = processor.calculate_ms_magnitude(north, east, vert, 1500, 100)
    """
    
    def __init__(self):
        """
        Initialiserer seismisk processor med standard parametre.
        
        Opsætter:
        - TauP model til præcise rejsetidsberegninger
        - Standard filterbånd til forskellige bølgetyper
        - Filter parametre optimeret til seismisk analyse
        """
        # Initialisér TauP model til rejsetidsberegning
        if ADVANCED_FEATURES:
            try:
                # iasp91 er standard Earth model til teleseismisk analyse
                self.taup_model = TauPyModel(model="iasp91")
            except:
                self.taup_model = None
        
        # Prædefinerede filterbånd optimeret til forskellige seismiske bølgetyper
        self.filter_bands = {
            'raw': None,  # Ingen filtrering - original data
            'broadband': (0.01, 25.0),  # Bred frekvens for generel analyse
            'p_waves': (1.0, 10.0),     # P-bølger: høj frekvens kompression
            's_waves': (0.5, 5.0),      # S-bølger: medium frekvens forskydning
            'surface': (0.02, 0.5),     # Overfladebølger: lav frekvens, kritisk for Ms
            'long_period': (0.005, 0.1), # Lang-periode: tektoniske signaler
            'teleseismic': (0.02, 2.0)  # Teleseismisk: optimeret til fjerne jordskælv
        }
        
        # Standard filter parametre baseret på seismologisk praksis
        self.filter_order = 4  # Butterworth filter orden - balance mellem skarphed og stabilitet
        self.spike_threshold = 5.0  # Z-score threshold - konservativ for at undgå false positives
    
    def apply_bandpass_filter(self, data, sampling_rate, low_freq, high_freq, order=None):
        """
        Anvender Butterworth båndpas filter på seismiske data med forbedret validering.
        
        Butterworth filter er foretrukket i seismologi for sin flade passband
        og predictable roll-off karakteristik. Zero-phase filtering (filtfilt)
        bevarer timing af seismiske faser.
        
        Args:
            data (array): Input seismogram
            sampling_rate (float): Sampling frekvens i Hz
            low_freq (float): Nedre corner frekvens i Hz
            high_freq (float): Øvre corner frekvens i Hz
            order (int, optional): Filter orden. Default bruger self.filter_order
            
        Returns:
            array: Filtreret seismogram med samme længde som input
            
        Raises:
            Warnings: Ved ugyldige frekvenser returneres original data
            
        Note:
            - Frekvenser justeres automatisk hvis de overstiger Nyquist
            - Zero-phase filtering bevarer seismiske fase timing
            - Robust fejlhåndtering forhindrer data tab
            
        Example:
            # Filter P-bølger fra 100 Hz data
            p_filtered = processor.apply_bandpass_filter(data, 100.0, 1.0, 10.0)
        """
        try:
            if order is None:
                order = self.filter_order
                
            # Beregn Nyquist frekvens - teoretisk maksimum
            nyquist = sampling_rate / 2.0
            max_safe_freq = nyquist * 0.95  # Brug 95% af Nyquist for stabilitet
            
            # Validering og justering af input frekvenser
            if low_freq >= max_safe_freq:
                warnings.warn(f"Lav frekvens ({low_freq} Hz) er for høj for sampling rate {sampling_rate} Hz. Filter ikke anvendt.")
                return data
            
            if high_freq > max_safe_freq:
                warnings.warn(f"Høj frekvens justeret fra {high_freq} Hz til {max_safe_freq:.2f} Hz for sampling rate {sampling_rate} Hz")
                high_freq = max_safe_freq
            
            if low_freq >= high_freq:
                warnings.warn(f"Lav frekvens ({low_freq}) skal være mindre end høj frekvens ({high_freq}). Filter ikke anvendt.")
                return data
            
            # Normaliser frekvenser til Nyquist (krav for scipy.signal)
            low_norm = low_freq / nyquist
            high_norm = high_freq / nyquist
            
            # Final validering af normaliserede frekvenser
            if low_norm <= 0 or high_norm >= 1 or low_norm >= high_norm:
                warnings.warn(f"Normaliserede frekvenser ugyldige: {low_norm:.3f}-{high_norm:.3f}. Filter ikke anvendt.")
                return data
            
            # Design Butterworth båndpas filter
            b, a = butter(order, [low_norm, high_norm], btype='band')
            
            # Anvend zero-phase filter for at bevare timing
            filtered_data = filtfilt(b, a, data)
            
            return filtered_data
            
        except Exception as e:
            warnings.warn(f"Filter fejl: {e}. Returnerer original data.")
            return data
    
    def remove_spikes(self, data, threshold=None, window_size=5):
        """
        Fjerner spikes (outliers) fra seismiske data med robust statistik.
        
        Bruger Modified Z-Score baseret på Median Absolute Deviation (MAD)
        som er mere robust mod outliers end standard deviation.
        Spikes erstattes med median-filtrerede værdier for at bevare
        kontinuitet i tidsserien.
        
        Args:
            data (array): Input seismogram
            threshold (float, optional): Z-score threshold. Default: self.spike_threshold
            window_size (int): Median filter vindue størrelse
            
        Returns:
            tuple: (cleaned_data, spike_info)
                cleaned_data: Data med spikes fjernet
                spike_info: Dictionary med spike statistikker
                
        Note:
            Modified Z-Score = 0.6745 * (x - median) / MAD
            hvor MAD = median(|x - median(x)|)
            
        Example:
            clean_data, info = processor.remove_spikes(noisy_data, threshold=5.0)
            print(f"Fjernet {info['num_spikes']} spikes ({info['spike_percentage']:.1f}%)")
        """
        try:
            if threshold is None:
                threshold = self.spike_threshold
            
            # Beregn robust statistik - mindre påvirket af outliers
            median_val = np.median(data)
            mad = np.median(np.abs(data - median_val))  # Median Absolute Deviation
            
            if mad == 0:
                # Hvis MAD er 0 (konstant signal), brug standard deviation
                modified_z_scores = np.abs(data - median_val) / (np.std(data) + 1e-10)
            else:
                # Standard Modified Z-Score formula
                modified_z_scores = 0.6745 * (data - median_val) / mad
            
            # Identificer spikes baseret på threshold
            spike_indices = np.abs(modified_z_scores) > threshold
            
            # Lav kopi af data for at undgå modification af original
            cleaned_data = data.copy()
            
            if np.any(spike_indices):
                # Erstat spikes med median filtered værdier for kontinuitet
                median_filtered = medfilt(data, kernel_size=window_size)
                cleaned_data[spike_indices] = median_filtered[spike_indices]
            
            # Kompiler spike statistikker til kvalitetsvurdering
            spike_info = {
                'num_spikes': np.sum(spike_indices),
                'spike_percentage': 100 * np.sum(spike_indices) / len(data),
                'max_z_score': np.max(np.abs(modified_z_scores)),
                'spike_indices': np.where(spike_indices)[0]
            }
            
            return cleaned_data, spike_info
            
        except Exception as e:
            print(f"Spike removal fejl: {e}")
            # Return original data med tom spike info ved fejl
            return data, {'num_spikes': 0, 'spike_percentage': 0, 'max_z_score': 0, 'spike_indices': np.array([])}
    
    def estimate_noise_level(self, waveform, p_arrival_time, sampling_rate, duration=60):
        """
        Estimerer støjniveau fra pre-event data til SNR beregning.
        
        Analyserer signal før P-bølge ankomst for at etablere baseline støjniveau.
        Dette er kritisk for SNR beregning og datakvalitetsvurdering.
        
        Args:
            waveform (array): Komplet seismogram
            p_arrival_time (float): P-bølge ankomst tid i sekunder
            sampling_rate (float): Sampling frekvens i Hz
            duration (float): Længde af pre-event analyse vindue i sekunder
            
        Returns:
            dict or None: Støj statistikker eller None hvis utilstrækkelig data
                - rms: Root Mean Square amplitude
                - std: Standard deviation
                - max: Maksimum amplitude
                - median: Median amplitude
                - mad: Median Absolute Deviation
                - samples: Antal samples analyseret
                - duration: Faktisk analyse varighed
                
        Note:
            - RMS er ofte foretrukket til SNR beregning
            - MAD er robust mod outliers i støj estimering
            
        Example:
            noise_stats = processor.estimate_noise_level(data, 120.5, 100.0, 60)
            if noise_stats:
                snr_db = 20 * log10(signal_rms / noise_stats['rms'])
        """
        try:
            pre_event_samples = int(duration * sampling_rate)
            p_sample = int(p_arrival_time * sampling_rate)
            
            # Håndter tilfælde hvor P-ankomst er tæt på data start
            if p_sample <= pre_event_samples:
                # Ikke nok pre-event data - brug hvad der er tilgængeligt
                noise_window = waveform[:p_sample] if p_sample > 0 else waveform[:int(len(waveform)*0.1)]
            else:
                # Ideelt tilfælde - fuld pre-event vindue
                noise_window = waveform[p_sample-pre_event_samples:p_sample]
            
            if len(noise_window) == 0:
                return None
            
            # Beregn omfattende støj statistikker
            noise_stats = {
                'rms': np.sqrt(np.mean(noise_window**2)),  # Root Mean Square - standard for SNR
                'std': np.std(noise_window),               # Standard deviation
                'max': np.max(np.abs(noise_window)),       # Peak amplitude
                'median': np.median(np.abs(noise_window)), # Median amplitude - robust
                'mad': np.median(np.abs(noise_window - np.median(noise_window))),  # MAD - robust spread
                'samples': len(noise_window),              # Antal samples brugt
                'duration': len(noise_window) / sampling_rate  # Faktisk analyse varighed
            }
            
            return noise_stats
            
        except Exception as e:
            print(f"Støj estimering fejl: {e}")
            return None
    
    def calculate_snr(self, signal, noise_level, window_length, sampling_rate):
        """
        Beregner Signal-to-Noise Ratio over tid med overlappende vinduer.
        
        SNR er kritisk for datakvalitetsvurdering og analysepålidelighed.
        Bruger overlappende vinduer for kontinuerlig SNR monitoring.
        
        Args:
            signal (array): Input seismogram
            noise_level (float): Reference støjniveau (typisk RMS fra pre-event)
            window_length (float): Analyse vindue længde i sekunder
            sampling_rate (float): Sampling frekvens i Hz
            
        Returns:
            tuple: (snr_db, time_centers)
                snr_db: SNR værdier i dB
                time_centers: Tid centre for hvert analyse vindue
                
        Note:
            SNR(dB) = 10 * log10(signal_power / noise_power)
            - SNR > 20 dB: Fremragende kvalitet
            - SNR 10-20 dB: God kvalitet  
            - SNR < 10 dB: Begrænset kvalitet
            
        Example:
            snr_values, times = processor.calculate_snr(data, noise_rms, 10.0, 100.0)
            high_quality_indices = snr_values > 15  # Find høj kvalitets segmenter
        """
        try:
            window_samples = int(window_length * sampling_rate)
            hop_samples = window_samples // 2  # 50% overlap for kontinuitet
            
            snr_values = []
            time_centers = []
            
            # Analyser signal med overlappende vinduer
            for start in range(0, len(signal) - window_samples, hop_samples):
                window = signal[start:start + window_samples]
                signal_power = np.mean(window**2)  # Beregn signal power
                
                # Undgå log(0) og beregn SNR i dB
                if signal_power > 0 and noise_level > 0:
                    snr_db = 10 * np.log10(signal_power / (noise_level**2))
                else:
                    snr_db = -60  # Meget lavt SNR for ugyldige data
                
                snr_values.append(snr_db)
                time_centers.append((start + window_samples/2) / sampling_rate)
            
            return np.array(snr_values), np.array(time_centers)
            
        except Exception as e:
            print(f"SNR beregning fejl: {e}")
            return np.array([]), np.array([])
    
    def process_waveform_with_filtering(self, waveform_data, filter_type='broadband', remove_spikes=True, calculate_noise=True):
        """
        Komplet waveform processing pipeline med avanceret filtrering.
        
        Integreret workflow der kombinerer alle processing steps:
        1. Spike detektion og fjernelse
        2. Filter application baseret på type
        3. Støj estimering fra pre-event data
        4. SNR beregning over hele signalet
        
        Args:
            waveform_data (dict): Standard waveform data struktur med:
                - 'displacement_data': Dict med komponenter
                - 'sampling_rate': Sampling frekvens
                - 'arrival_times': Dict med P/S/Surface ankomsttider
            filter_type (str): Filter type fra self.filter_bands
            remove_spikes (bool): Om spikes skal fjernes
            calculate_noise (bool): Om støj skal estimeres og SNR beregnes
            
        Returns:
            dict: Omfattende processed data struktur med:
                - 'original_data': Uprocesseret data
                - 'filtered_data': Filtreret data for hver komponent
                - 'spike_info': Spike detektion resultater
                - 'noise_stats': Støj statistikker
                - 'snr_data': SNR over tid
                - 'filter_used': Anvendt filter type
                - 'filter_params': Filter parametre
                
        Example:
            processed = processor.process_waveform_with_filtering(
                waveform_data, 
                filter_type='surface',  # Optimal til Ms beregning
                remove_spikes=True,
                calculate_noise=True
            )
        """
        try:
            sampling_rate = waveform_data['sampling_rate']
            displacement_data = waveform_data['displacement_data']
            
            # Initialisér komplet output struktur
            processed_data = {
                'original_data': displacement_data.copy(),
                'filtered_data': {},
                'spike_info': {},
                'noise_stats': {},
                'filter_used': filter_type,
                'filter_params': None,
                'snr_data': {}
            }
            
            # Hent og validér filter parametre
            if filter_type in self.filter_bands and self.filter_bands[filter_type] is not None:
                low_freq, high_freq = self.filter_bands[filter_type]
                processed_data['filter_params'] = {'low': low_freq, 'high': high_freq}
            else:
                processed_data['filter_params'] = None
            
            # Processer hver seismiske komponent individuelt
            for component in ['north', 'east', 'vertical']:
                if component not in displacement_data:
                    continue
                
                signal = displacement_data[component]
                
                # Step 1: Spike detektion og fjernelse (hvis aktiveret)
                if remove_spikes:
                    signal, spike_info = self.remove_spikes(signal)
                    processed_data['spike_info'][component] = spike_info
                
                # Step 2: Filter application baseret på valgt type
                if processed_data['filter_params'] is not None:
                    signal = self.apply_bandpass_filter(
                        signal, sampling_rate, 
                        processed_data['filter_params']['low'],
                        processed_data['filter_params']['high']
                    )
                
                processed_data['filtered_data'][component] = signal
            
            # Step 3: Støj analyse og SNR beregning (hvis P-ankomst kendes)
            if calculate_noise and 'arrival_times' in waveform_data:
                p_arrival = waveform_data['arrival_times'].get('P')
                if p_arrival is not None:
                    for component in processed_data['filtered_data']:
                        # Estimér støjniveau fra pre-event data
                        noise_stats = self.estimate_noise_level(
                            processed_data['filtered_data'][component],
                            p_arrival, sampling_rate
                        )
                        if noise_stats:
                            processed_data['noise_stats'][component] = noise_stats
                            
                            # Beregn kontinuerlig SNR over hele signalet
                            snr_db, snr_times = self.calculate_snr(
                                processed_data['filtered_data'][component],
                                noise_stats['rms'], 10.0, sampling_rate
                            )
                            processed_data['snr_data'][component] = {
                                'snr_db': snr_db,
                                'times': snr_times
                            }
            
            return processed_data
            
        except Exception as e:
            print(f"Waveform processing fejl: {e}")
            return None
    
    def calculate_wave_arrivals(self, distance_deg, depth_km):
        """
        Beregner præcise P, S, og overfladebølge ankomsttider med TauP model.
        
        Bruger standard iasp91 Earth model til rejsetidsberegning.
        Inkluderer fallback beregninger hvis TauP fejler.
        
        Args:
            distance_deg (float): Epicentral afstand i grader
            depth_km (float): Jordskælv dybde i kilometer
            
        Returns:
            dict: Ankomsttider i sekunder
                - 'P': P-bølge ankomst
                - 'S': S-bølge ankomst  
                - 'Surface': Overfladebølge ankomst
                
        Note:
            Fallback hastigheder hvis TauP fejler:
            - P-bølger: ~8.0 km/s
            - S-bølger: ~4.5 km/s
            - Overfladebølger: ~3.5 km/s
            
        Example:
            arrivals = processor.calculate_wave_arrivals(45.2, 15.0)
            print(f"P: {arrivals['P']:.1f}s, S: {arrivals['S']:.1f}s")
        """
        arrivals = {'P': None, 'S': None, 'Surface': None}
        
        # Forsøg TauP model beregning først (mest præcis)
        if self.taup_model:
            try:
                arrivals_taup = self.taup_model.get_travel_times(
                    source_depth_in_km=depth_km,
                    distance_in_degree=distance_deg,
                    phase_list=['P', 'S']
                )
                
                # Parser TauP resultater og tag første ankomst af hver type
                for arrival in arrivals_taup:
                    phase_name = arrival.name
                    
                    # P-bølge faser (direkte, refrakterede, etc.)
                    if phase_name in ['P', 'Pn', 'Pg'] and arrivals['P'] is None:
                        arrivals['P'] = arrival.time
                    # S-bølge faser  
                    elif phase_name in ['S', 'Sn', 'Sg'] and arrivals['S'] is None:
                        arrivals['S'] = arrival.time
                
                # Overfladebølger beregnes altid med empirisk formel
                if distance_deg > 5:  # Kun for teleseismiske afstande
                    arrivals['Surface'] = distance_deg * 111.32 / 3.5  # ~3.5 km/s
                    
            except Exception as e:
                print(f"TauP calculation error: {e}")
        
        # Fallback beregninger med standard hastigheder
        if arrivals['P'] is None:
            arrivals['P'] = distance_deg * 111.32 / 8.0  # P-bølge ~8 km/s
        if arrivals['S'] is None:
            arrivals['S'] = distance_deg * 111.32 / 4.5  # S-bølge ~4.5 km/s
        if arrivals['Surface'] is None:
            arrivals['Surface'] = distance_deg * 111.32 / 3.5  # Surface ~3.5 km/s
        
        return arrivals
    
    def calculate_ms_magnitude(self, waveform_north_mm, waveform_east_mm, waveform_vertical_mm, distance_km, sampling_rate, period=20.0):
        """
        Beregner Ms magnitude fra overfladebølger efter IASPEI standarder.
        
        Implementerer både klassisk Ms (horizontal) og moderne Ms_20 (vertikal)
        efter IASPEI 2013 standarder. Bruger den største amplitude på hver
        komponent type til magnitude beregning.
        
        Args:
            waveform_north_mm (array): Nord komponent displacement i mm
            waveform_east_mm (array): Øst komponent displacement i mm  
            waveform_vertical_mm (array): Vertikal komponent displacement i mm
            distance_km (float): Epicentral afstand i km
            sampling_rate (float): Data sampling frekvens i Hz
            period (float): Reference periode i sekunder (standard: 20s)
            
        Returns:
            tuple: (magnitude, explanation)
                magnitude: Ms værdi (float) eller None ved fejl
                explanation: Detaljeret beregnings forklaring (str)
                
        Note:
            Ms formel: Ms = log₁₀(A/T) + 1.66×log₁₀(Δ) + 3.3
            hvor:
            - A = maksimum amplitude i μm
            - T = periode i sekunder (20s reference)
            - Δ = epicentral afstand i grader
            - Konstanter fra empirisk kalibrering
            
        Standards:
            - Klassisk Ms: Bruger største horizontale komponent
            - Ms_20 (IASPEI 2013): Foretrækker vertikal komponent
            - Magnitude range: 4.0 ≤ Ms ≤ 8.5
            
        Example:
            ms_mag, explanation = processor.calculate_ms_magnitude(
                north_mm, east_mm, vert_mm, 1500.0, 100.0
            )
            if ms_mag:
                print(f"Ms magnitude: {ms_mag}")
        """
        try:
            # Validér input data
            if len(waveform_north_mm) == 0 or len(waveform_east_mm) == 0 or len(waveform_vertical_mm) == 0:
                return None, "No waveform data"
            
            # Konverter mm til μm (mikrometers) som krævet af Ms formel
            north_um = waveform_north_mm * 1000
            east_um = waveform_east_mm * 1000
            vertical_um = waveform_vertical_mm * 1000
            
            # Find maksimum amplitude på hver komponent
            max_amplitude_north = np.max(np.abs(north_um))
            max_amplitude_east = np.max(np.abs(east_um))
            max_amplitude_vertical = np.max(np.abs(vertical_um))
            
            # KLASSISK Ms: Brug største horizontale komponent (pre-2013 standard)
            max_amplitude_horizontal = max(max_amplitude_north, max_amplitude_east)
            dominant_horizontal = "North" if max_amplitude_north > max_amplitude_east else "East"
            
            # MODERNE Ms_20: Brug vertikal komponent (IASPEI 2013 standard)
            max_amplitude_ms20 = max_amplitude_vertical
            
            # Beregn afstand og fælles termer
            distance_degrees = distance_km / 111.32  # km til grader konvertering
            log_distance = np.log10(distance_degrees)
            distance_correction = 1.66 * log_distance + 3.3  # Empirisk kalibreret
            
            # Klassisk Ms beregning (horizontal)
            if max_amplitude_horizontal > 0:
                log_amp_period_horizontal = np.log10(max_amplitude_horizontal / period)
                ms_horizontal = log_amp_period_horizontal + distance_correction
                ms_horizontal = max(4.0, min(8.5, ms_horizontal))  # Begræns til fysisk range
            else:
                ms_horizontal = None
            
            # Moderne Ms_20 beregning (vertikal)
            if max_amplitude_ms20 > 0:
                log_amp_period_vertical = np.log10(max_amplitude_ms20 / period)
                ms_vertical = log_amp_period_vertical + distance_correction
                ms_vertical = max(4.0, min(8.5, ms_vertical))  # Begræns til fysisk range
            else:
                ms_vertical = None
            
            # Bestem primær værdi (foretrækker moderne Ms_20 hvis tilgængelig)
            if ms_vertical is not None and ms_horizontal is not None:
                # Brug vertikal (Ms_20) som primær, men vis begge
                primary_ms = ms_vertical
                comparison_note = f"Ms_20 (vertical): {ms_vertical:.1f} | Ms (horizontal {dominant_horizontal}): {ms_horizontal:.1f}"
            elif ms_vertical is not None:
                primary_ms = ms_vertical
                comparison_note = f"Ms_20 (vertical): {ms_vertical:.1f}"
            elif ms_horizontal is not None:
                primary_ms = ms_horizontal
                comparison_note = f"Ms (horizontal {dominant_horizontal}): {ms_horizontal:.1f}"
            else:
                return None, "Zero amplitudes on all components"
            
            # Generer detaljeret forklaring til brugerforståelse
            explanation = f"""
            **Ms Magnitude Beregning (IASPEI Standards):**
            
            **Formel:** Ms = log₁₀(A/T) + 1.66×log₁₀(Δ) + 3.3
            
            **Komponent Amplituder:**
            - Nord komponent max: {max_amplitude_north:.1f} μm
            - Øst komponent max: {max_amplitude_east:.1f} μm  
            - Vertikal komponent max: {max_amplitude_vertical:.1f} μm
            - **Dominerende horizontal: {dominant_horizontal}**
            
            **Beregninger:**
            - Periode (T): {period:.1f} s
            - Afstand (Δ): {distance_degrees:.2f}°
            - log₁₀(Δ): {log_distance:.3f}
            - Afstandskorrektion: 1.66×{log_distance:.3f} + 3.3 = {distance_correction:.3f}
            
            **Resultater:**
            {comparison_note}
            
            **Standard Information:**
            - **Ms_20 (2013 IASPEI)**: Bruger vertikal komponent - moderne standard
            - **Ms (klassisk)**: Bruger største horizontale komponent - historisk standard
            - **Primær værdi**: {primary_ms:.1f} ({"Ms_20" if ms_vertical is not None and primary_ms == ms_vertical else "Ms klassisk"})
            
            *Note: Ms_20 (vertikal) foretrækkes ifølge IASPEI 2013 standarder.*
            """
            
            return round(primary_ms, 1), explanation
            
        except Exception as e:
            return None, f"Calculation error: {e}"
    
    def calculate_surface_wave_fft(self, waveform_mm, sampling_rate, surface_arrival_time):
        """
        Beregner FFT spektral analyse af overfladebølger med peak identifikation.
        
        Analyserer frekvens indhold af overfladebølger for at:
        - Identificere dominant periode (skal være ~20s for Ms)
        - Evaluere signal kvalitet
        - Understøtte magnitude beregning
        
        Args:
            waveform_mm (array): Overfladebølge displacement i mm
            sampling_rate (float): Sampling frekvens i Hz
            surface_arrival_time (float): Overfladebølge ankomst tid i sekunder
            
        Returns:
            tuple: (periods, fft_amplitudes, peak_period, peak_amplitude)
                periods: Periode array i sekunder
                fft_amplitudes: FFT amplitude spektrum
                peak_period: Dominerende periode omkring 20s
                peak_amplitude: Amplitude ved peak periode
                
        Note:
            - Analyserer 10 minutter efter surface arrival
            - Søger peak i 10-40s periode range
            - Default til 20s hvis ingen klar peak
            
        Example:
            periods, amps, peak_p, peak_a = processor.calculate_surface_wave_fft(
                vertical_mm, 100.0, 180.5
            )
            if abs(peak_p - 20.0) < 2.0:
                print("Optimal periode for Ms beregning")
        """
        try:
            # Definer analyse vindue: fra surface arrival til 10 minutter efter
            start_idx = int(surface_arrival_time * sampling_rate)
            end_idx = start_idx + int(600 * sampling_rate)  # 10 minutter = 600 sekunder
            
            # Validér indekser
            if start_idx >= len(waveform_mm) or start_idx < 0:
                return None, None, None, None
            
            end_idx = min(end_idx, len(waveform_mm))
            surface_wave_data = waveform_mm[start_idx:end_idx]
            
            if len(surface_wave_data) < 100:  # Kræv tilstrækkelig data
                return None, None, None, None
            
            # Beregn FFT spektrum
            fft_data = np.abs(fft(surface_wave_data))
            freqs = fftfreq(len(surface_wave_data), 1/sampling_rate)
            
            # Brug kun positive frekvenser (FFT er symmetrisk)
            positive_freqs = freqs[:len(freqs)//2]
            positive_fft = fft_data[:len(fft_data)//2]
            
            # Konverter frekvenser til perioder (T = 1/f)
            periods = 1.0 / positive_freqs[1:]  # Skip DC komponent (freq=0)
            fft_amplitudes = positive_fft[1:]
            
            # Søg efter peak omkring 20s periode (optimal for Ms)
            period_mask = (periods >= 10) & (periods <= 40)  # Søg i 10-40s range
            if np.any(period_mask):
                search_periods = periods[period_mask]
                search_amplitudes = fft_amplitudes[period_mask]
                
                # Find højeste amplitude i søge område
                peak_idx = np.argmax(search_amplitudes)
                peak_period = search_periods[peak_idx]
                peak_amplitude = search_amplitudes[peak_idx]
            else:
                # Fallback til 20s hvis ingen peak fundet
                peak_period = 20.0
                peak_amplitude = np.max(fft_amplitudes) if len(fft_amplitudes) > 0 else 1.0
            
            return periods, fft_amplitudes, peak_period, peak_amplitude
            
        except Exception as e:
            print(f"FFT calculation error: {e}")
            return None, None, None, None

    def validate_earthquake_timing(self, earthquake, station, waveform_data):
        """
        Validerer at seismisk timing giver fysisk mening.
        
        Kontrollerer om implicit P-bølge hastighed er realistisk baseret på
        observeret ankomsttid og epicentral afstand. Dette hjælper med at
        identificere timing problemer i data.
        
        Args:
            earthquake (dict): Jordskælv metadata
            station (dict): Station metadata med afstand
            waveform_data (dict): Waveform data (ikke brugt direkte)
            
        Returns:
            tuple: (is_valid, message, validation_info)
                is_valid: Boolean om timing er fysisk realistisk
                message: Forklarende besked
                validation_info: Detaljeret validerings data
                
        Note:
            Fysiske P-bølge hastigheds grænser:
            - Minimum: 5.8 km/s (øvre kappe)
            - Maksimum: 13.7 km/s (indre kerne)
            
        Example:
            valid, msg, info = processor.validate_earthquake_timing(eq, sta, data)
            if not valid:
                print(f"Timing problem: {msg}")
                print(f"Observed velocity: {info['implicit_velocity']:.1f} km/s")
        """
        distance_km = station['distance_km']
        p_arrival_observed = station.get('p_arrival')
        
        if not p_arrival_observed:
            return False, "Ingen P-ankomst beregnet", None
        
        # Beregn implicit hastighed fra observeret timing
        implicit_velocity = distance_km / p_arrival_observed
        
        # Fysiske grænser baseret på Earth struktur
        min_velocity = 5.8  # km/s - øvre kappe minimum
        max_velocity = 13.7  # km/s - indre kerne maksimum
        
        # Kompiler validerings information
        validation_info = {
            'implicit_velocity': implicit_velocity,
            'distance_km': distance_km,
            'p_arrival_time': p_arrival_observed,
            'min_expected_velocity': min_velocity,
            'max_expected_velocity': max_velocity,
            'realistic_p_range': (distance_km / max_velocity, distance_km / min_velocity)
        }
        
        # Evaluér mod fysiske grænser
        if implicit_velocity < min_velocity:
            return False, f"P-hastighed {implicit_velocity:.1f} km/s er for lav (< {min_velocity} km/s) - mulig timing fejl", validation_info
        
        if implicit_velocity > max_velocity:
            return False, f"P-hastighed {implicit_velocity:.1f} km/s er for høj (> {max_velocity} km/s) - mulig timing fejl", validation_info
        
        return True, f"P-hastighed {implicit_velocity:.1f} km/s er realistisk", validation_info
    
    def create_p_wave_zoom_plot(self, waveform_data, station, processed_data):
        """
        Opretter detaljeret P-bølge analyse plot med STA/LTA detektion.
        
        Genererer zoom visning omkring P-bølge ankomst med automatisk
        detektion for at hjælpe med timing validering og kvalitetsvurdering.
        
        Args:
            waveform_data (dict): Original waveform data
            station (dict): Station metadata med ankomsttider
            processed_data (dict): Filtreret data fra processing pipeline
            
        Returns:
            tuple: (fig, peak_info)
                fig: Plotly figure med P-bølge analyse
                peak_info: Liste med detektion resultater per komponent
                
        Note:
            - Zoom vindue: ±60 sekunder omkring teoretisk P-ankomst
            - STA/LTA detektion med 2s/10s vinduer
            - Threshold: STA/LTA > 3.0 for detektion
            
        Example:
            p_fig, peaks = processor.create_p_wave_zoom_plot(data, sta, processed)
            for peak in peaks:
                print(f"{peak['component']}: {peak['sta_lta']:.1f} ratio")
        """
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            
            times = waveform_data['time']
            sampling_rate = waveform_data['sampling_rate']
            p_arrival_theoretical = station.get('p_arrival')
            
            if not p_arrival_theoretical:
                return None, None
            
            # Definer zoom vindue omkring P-ankomst (±60 sekunder)
            p_start_time = max(0, p_arrival_theoretical - 60)
            p_end_time = p_arrival_theoretical + 60
            
            # Konverter til sample indekser
            start_idx = int(p_start_time * sampling_rate)
            end_idx = int(p_end_time * sampling_rate)
            start_idx = max(0, min(start_idx, len(times)-1))
            end_idx = max(start_idx+1, min(end_idx, len(times)))
            
            # Udtræk zoom data
            zoom_times = times[start_idx:end_idx]
            zoom_times_relative = zoom_times - p_arrival_theoretical  # Relativ til P-ankomst
            
            # Brug filtrerede data til P-bølge analyse
            if processed_data and 'filtered_data' in processed_data:
                filtered_data = processed_data['filtered_data']
            else:
                filtered_data = waveform_data['displacement_data']
            
            # Zoom data for hver komponent
            zoom_data = {}
            peak_info = []
            
            # Opret 3-panel subplot for komponenter
            fig = make_subplots(
                rows=3, cols=1,
                subplot_titles=['North Komponent', 'East Komponent', 'Vertical Komponent'],
                vertical_spacing=0.08,
                shared_xaxes=True
            )
            
            colors = ['red', 'green', 'blue']
            components = ['north', 'east', 'vertical']
            
            # Plot hver komponent med STA/LTA analyse
            for i, (component, color) in enumerate(zip(components, colors)):
                if component in filtered_data:
                    # Udtræk komponent zoom data
                    component_data = filtered_data[component][start_idx:end_idx]
                    zoom_data[component] = component_data
                    
                    # Plot seismogram
                    fig.add_trace(
                        go.Scatter(
                            x=zoom_times_relative,
                            y=component_data,
                            mode='lines',
                            name=f'{component.capitalize()}',
                            line=dict(color=color, width=1),
                            showlegend=True
                        ),
                        row=i+1, col=1
                    )
                    
                    # Udfør STA/LTA detektion
                    sta_lta_ratio, detected_time = self._calculate_sta_lta_simple(
                        component_data, sampling_rate, zoom_times_relative
                    )
                    
                    # Markér detekteret P-ankomst hvis signifikant
                    if detected_time is not None:
                        fig.add_vline(
                            x=detected_time,
                            line=dict(color=color, width=2, dash='solid'),
                            annotation_text=f"P? ({sta_lta_ratio:.1f})",
                            row=i+1, col=1
                        )
                        
                        # Gem peak information
                        peak_info.append({
                            'component': component,
                            'time': detected_time + p_arrival_theoretical,  # Absolut tid
                            'delay': detected_time,  # Relativ til teoretisk
                            'sta_lta': sta_lta_ratio
                        })
                    else:
                        # Ingen klar detektion - brug teoretisk tid
                        peak_info.append({
                            'component': component,
                            'time': p_arrival_theoretical,
                            'delay': 0.0,
                            'sta_lta': 1.0
                        })
                
                # Markér teoretisk P-ankomst på alle paneler
                fig.add_vline(
                    x=0,
                    line=dict(color='black', width=3, dash='dash'),
                    annotation_text="Teoretisk P",
                    row=i+1, col=1
                )
            
            # Opdater layout for optimal visning
            fig.update_layout(
                title=f"P-bølge Zoom Analyse - {station['network']}.{station['station']}",
                height=600,
                showlegend=True
            )
            
            # Opdater akse labels
            fig.update_xaxes(title_text="Tid relativ til teoretisk P-ankomst (s)", row=3, col=1)
            
            for i in range(1, 4):
                fig.update_yaxes(title_text="Amplitude (mm)", row=i, col=1)
            
            return fig, peak_info
            
        except Exception as e:
            print(f"P-wave plot fejl: {e}")
            return None, None
    
    def _calculate_sta_lta_simple(self, data, sampling_rate, time_array):
        """
        Implementerer simpel STA/LTA (Short Term Average / Long Term Average) detektion.
        
        STA/LTA er standard metode til automatisk P-bølge detektion i seismologi.
        Sammenligner kort-periode energi (signal) med lang-periode energi (baggrund).
        
        Args:
            data (array): Input seismogram
            sampling_rate (float): Sampling frekvens i Hz
            time_array (array): Tid array for plotting
            
        Returns:
            tuple: (max_ratio, best_time)
                max_ratio: Højeste STA/LTA ratio fundet
                best_time: Tid for højeste ratio (hvis > threshold)
                
        Note:
            Standard parametre:
            - STA vindue: 2.0 sekunder (signal karakteristik)
            - LTA vindue: 10.0 sekunder (baggrunds karakteristik)  
            - Detektion threshold: 3.0 (empirisk optimeret)
            
        Algorithm:
            1. Beregn squared data (power)
            2. For hver position: STA = mean(power_short), LTA = mean(power_long)
            3. Ratio = STA / LTA
            4. Find maksimum ratio > threshold
            
        Example:
            ratio, time = processor._calculate_sta_lta_simple(p_data, 100.0, times)
            if ratio > 3.0:
                print(f"P-ankomst detekteret ved {time:.1f}s (ratio: {ratio:.1f})")
        """
        try:
            # Standard STA/LTA parametre optimeret til P-bølge detektion
            sta_length = 2.0  # sekunder - kort nok til at fange P-onset
            lta_length = 10.0  # sekunder - lang nok til stabil baggrund
            
            # Konverter til samples
            sta_samples = int(sta_length * sampling_rate)
            lta_samples = int(lta_length * sampling_rate)
            
            # Validér tilstrækkelig data længde
            if len(data) < lta_samples + sta_samples:
                return 1.0, None
            
            # Beregn power (squared amplitude) for energi detektion
            data_squared = data ** 2
            max_ratio = 1.0
            best_time = None
            
            # Scan gennem data med overlappende vinduer
            for i in range(lta_samples, len(data) - sta_samples):
                # LTA: Long Term Average (baggrunds energi)
                lta_window = data_squared[i-lta_samples:i]
                lta = np.mean(lta_window)
                
                # STA: Short Term Average (signal energi)
                sta_window = data_squared[i:i+sta_samples]
                sta = np.mean(sta_window)
                
                # Beregn STA/LTA ratio (undgå division med nul)
                if lta > 0:
                    ratio = sta / lta
                    if ratio > max_ratio:
                        max_ratio = ratio
                        best_time = time_array[i] if i < len(time_array) else None
            
            # Returner kun detektion hvis ratio er signifikant højere end baggrund
            if max_ratio > 3.0 and best_time is not None:
                return max_ratio, best_time
            else:
                return max_ratio, None
                
        except Exception as e:
            print(f"STA/LTA fejl: {e}")
            return 1.0, None


class StreamlinedDataManager:
    """
    Avanceret data manager til IRIS integration med FIXED station finding og timing.
    
    Håndterer alle aspekter af seismisk data management:
    - IRIS FDSN client forbindelse og konfiguration
    - Intelligent jordskælv catalog søgning 
    - Optimeret station udvælgelse med geografisk distribution
    - Waveform download med præcis timing korrektion
    - Excel eksport med komplet metadata
    
    Denne klasse er kritisk for data kvalitet og timing præcision i analyser.
    """
    
    def __init__(self):
        """
        Initialiserer data manager med IRIS forbindelse og processor.
        
        Opsætter:
        - Enhanced seismic processor til avanceret analyse
        - IRIS FDSN client til data adgang
        - Automatisk forbindelsestest
        """
        self.processor = EnhancedSeismicProcessor()
        self.client = None
        self.connect_to_iris()
        
    
    def connect_to_iris(self):
        """
        Etablerer forbindelse til IRIS Data Management Center.
        
        IRIS er det primære globale arkiv for seismologiske data.
        Bruger FDSN (Federation of Digital Seismograph Networks) protocol.
        
        Returns:
            bool: True hvis forbindelse succesfyldt, False ellers
            
        Note:
            - 15 sekunder timeout for netværks stabilitet
            - Automatisk fejlrapportering til bruger interface
            
        Example:
            if data_manager.connect_to_iris():
                print("IRIS forbindelse klar til data hentning")
        """
        try:
            # Etabler FDSN client med IRIS Data Management Center
            self.client = Client("IRIS", timeout=15)
            return True
        except Exception as e:
            st.error(f"❌ Failed to connect to IRIS: {e}")
            return False
    
    # fetch_latest_earthquakes med korrekt tidslogik
    def fetch_latest_earthquakes(self, magnitude_range=(6.0, 9.2), year_range=(2000, 2025), depth_range=(1, 750), limit=25):
        """
        OPDATERET: Henter jordskælv med magnitude range og årstal filtrering.
        Søger fra nutid og tilbage til start_year.
        
        Args:
            magnitude_range (tuple): (min_magnitude, max_magnitude) (default: (6.0, 8.5))
            year_range (tuple): (start_year, end_year) årstal (default: (1990, 2025))
            limit (int): Maksimum antal jordskælv at returnere (default: 25)
        """
        if not self.client:
            return []
        
        try:
            progress_placeholder = st.empty()
            min_depth_km, max_depth_km = depth_range
            start_year, end_year = year_range
            min_magnitude, max_magnitude = magnitude_range
            
            # Vis brugervenlig information
            #progress_placeholder.info(f"🔍 Søger jordskælv M {min_magnitude:.1f}-{max_magnitude:.1f} fra {start_year} til {end_year}...")
            
            # RETTET: Korrekt tidslogik - fra start_year til nutid
            from datetime import datetime
            current_year = datetime.now().year
            
            # Brug den tidligste og seneste år korrekt
            earliest_year = min(start_year, end_year)
            latest_year = min(max(start_year, end_year), current_year)  # Ikke frem i tiden
            
            start_time = UTCDateTime(f"{earliest_year}-01-01T00:00:00")
            end_time = UTCDateTime(f"{latest_year + 1}-01-01T00:00:00")  # +1 for at inkludere hele slutåret
            
            try:
                # Forespørg IRIS med magnitude range og tidsperiode
                catalog = self.client.get_events(
                    starttime=start_time,
                    endtime=end_time,
                    minmagnitude=min_magnitude,
                    maxmagnitude=max_magnitude,
                    mindepth=min_depth_km, 
                    maxdepth=max_depth_km, 
                    orderby="time",
                    limit=500
                )
                
                if len(catalog) > 0:
                    earthquakes = self._process_catalog(catalog)
                    earthquakes.sort(key=lambda x: x['time'], reverse=True)  # Nyeste først
                    final_earthquakes = earthquakes[:limit]
                    
                    #progress_placeholder.success(f"✅ Fandt {len(final_earthquakes)} jordskælv")
                    return final_earthquakes
                else:
                    progress_placeholder.warning("⚠️ Ingen jordskælv fundet i den valgte periode og magnitude range")
                    return []
            
            except Exception as search_error:
                #progress_placeholder.error(f"❌ Søgning fejlede: {search_error}")
                return []
            
        except Exception as e:
            st.error(f"❌ Generel fejl: {e}")
            return []
    
    def _format_time_display(self, days):
        """Helper funktion til tid formatering"""
        if days == 0:
            return "i dag"
        elif days == 1:
            return "1 dag"
        elif days <= 30:
            return f"{days} dage"
        elif days <= 365:
            months = days // 30
            return f"~{months} måneder"
        else:
            years = days // 365
            return f"~{years} år"
    def _process_catalog(self, catalog):
        """
        Processerer ObsPy event catalog til standard dictionary format.
        
        Konverterer ObsPy catalog objekter til standardiseret format
        der er kompatibelt med resten af applikationen. Håndterer
        forskellige magnitude attribut navne på tværs af data centre.
        
        Args:
            catalog: ObsPy event catalog
            
        Returns:
            list: Liste af standardiserede jordskælv dictionaries
            
        Note:
            - Automatisk magnitude attribut detektion
            - Robust håndtering af manglende data
            - Konsistent tid og position formatting
            
        Example:
            earthquakes = manager._process_catalog(iris_catalog)
        """
        earthquakes = []
        events = catalog.events if hasattr(catalog, 'events') else catalog
        
        # Automatisk detektion af magnitude attribut navn
        # Forskellige data centre bruger forskellige navne
        working_mag_attr = 'magnitude'
        if len(events) > 0 and hasattr(events[0], 'magnitudes') and len(events[0].magnitudes) > 0:
            test_mag = events[0].magnitudes[0]
            for attr_name in ['magnitude', 'mag', 'magnitude_value', 'value']:
                if hasattr(test_mag, attr_name):
                    try:
                        val = getattr(test_mag, attr_name)
                        if val is not None:
                            working_mag_attr = attr_name
                            break
                    except:
                        continue
        
        # Processer hvert event i catalog
        for i, event in enumerate(events):
            try:
                # Hent origin information (hypocentrum)
                origin = event.preferred_origin() or event.origins[0]
                if origin is None or origin.latitude is None or origin.longitude is None:
                    continue  # Skip events uden valid position
                
                # Ekstrahér magnitude med robust attribut håndtering
                magnitude_value = None
                if hasattr(event, 'magnitudes') and len(event.magnitudes) > 0:
                    try:
                        mag_obj = event.magnitudes[0]
                        if hasattr(mag_obj, working_mag_attr):
                            magnitude_value = float(getattr(mag_obj, working_mag_attr))
                    except:
                        continue  # Skip events uden valid magnitude
                
                if magnitude_value is None:
                    continue
                
                # Håndter event tid med fallback
                try:
                    event_time = origin.time.datetime
                except:
                    event_time = datetime.now()  # Fallback til nuværende tid
                
                # Opret standardiseret event dictionary
                eq_dict = {
                    'index': len(earthquakes),  # Unikt index til GUI
                    'magnitude': magnitude_value,
                    'latitude': float(origin.latitude),
                    'longitude': float(origin.longitude),
                    'depth_km': float(origin.depth / 1000.0) if origin.depth else 10.0,  # m til km
                    'time': event_time,
                    'description': f"M{magnitude_value:.1f} {event_time.strftime('%d %b %Y')}",
                    'obspy_event': event  # Bevar original ObsPy objekt til videre analyse
                }
                
                earthquakes.append(eq_dict)
                
            except Exception:
                continue  # Skip problematiske events
        
        return earthquakes
    
    def find_stations_for_earthquake(self, earthquake, min_distance_km=800, max_distance_km=2200, target_stations=5):
        """
        Finder optimal stationer til seismisk analyse med intelligent udvælgelse.
        
        Søger efter 4 analyse-klar stationer i optimal teleseismisk afstand (800-2200 km).
        Bruger prioriterede netværk og geografisk distribution for bedste analyse kvalitet.
        
        Args:
            earthquake (dict): Jordskælv metadata
            min_distance_km (int): Minimum afstand - undgår direkte bølger (default: 800)
            max_distance_km (int): Maksimum afstand - før core shadow zone (default: 2200)
            target_stations (int): Ønsket antal stationer (default: 5)
            
        Returns:
            list: Liste af optimerede station dictionaries med ankomsttider
            
        Note:
            Afstands rationale:
            - < 800 km: Direkte bølger, kompleks kinematik
            - 800-2200 km: Optimal teleseismisk zone
            - > 2200 km: Core shadow zone, svagere signaler
            
        Network Priority:
            1. IU/II: Global Seismographic Network (højeste kvalitet)
            2. G: GEOSCOPE (Frankrig, høj kvalitet)
            3. GE: GEOFON (Tyskland, pålidelig)
            4. CN/US/GT: Regionale netværk (god dækning)
            
        Example:
            stations = manager.find_stations_for_earthquake(eq, 800, 2200, 4)
            for sta in stations:
                print(f"{sta['network']}.{sta['station']}: {sta['distance_km']:.0f} km")
        """
        if not self.client:
            st.error("❌ Ingen IRIS forbindelse")
            return self._fallback_station_list_optimized(earthquake, min_distance_km, max_distance_km, target_stations)
        
        eq_lat = earthquake['latitude']
        eq_lon = earthquake['longitude']
        eq_depth = earthquake['depth_km']
        eq_time = earthquake['obspy_event'].preferred_origin().time
        
        # Konverter km til grader (ca. 111.32 km per grad)
        min_distance_deg = min_distance_km / 111.32
        max_distance_deg = max_distance_km / 111.32
        
        progress_placeholder = st.empty()
        progress_placeholder.info(f"🔍 Søger {target_stations} analyse-klar stationer (800-2200 km)...")
        
        try:
            # Prioriterede netværk baseret på data kvalitet og tilgængelighed
            priority_networks = [
                'IU',  # Global Seismographic Network - højeste prioritet
                'II',  # Global Seismographic Network  
                'G',   # GEOSCOPE - fransk globalt netværk
                'GE',  # GEOFON - tysk globalt netværk
                'CN',  # Canadian National Seismograph Network
                'US',  # United States National Seismograph Network
                'GT'   # Global Telemetered Seismograph Network
            ]
            
            all_stations = []
            
            # Søg i hvert prioriteret netværk
            for network_code in priority_networks:
                if len(all_stations) >= target_stations * 3:  # Få ekstra til udvælgelse
                    break
                    
                try:
                    # Udvidet geografisk søgning for at fange alle relevante stationer
                    lat_buffer = max_distance_deg * 1.2  # Ekstra margin
                    lon_buffer = max_distance_deg * 1.2
                    
                    # Forespørg IRIS station inventory
                    inventory = self.client.get_stations(
                        network=network_code,
                        starttime=eq_time - 86400,  # 1 dag før
                        endtime=eq_time + 86400,    # 1 dag efter
                        level="station",
                        minlatitude=max(-90, eq_lat - lat_buffer),
                        maxlatitude=min(90, eq_lat + lat_buffer),
                        minlongitude=max(-180, eq_lon - lon_buffer),
                        maxlongitude=min(180, eq_lon + lon_buffer),
                        channel="*H*"  # Kun høj sample rate channels
                    )
                    
                    # Processer inventory resultater
                    for network in inventory:
                        for station in network:
                            try:
                                # Beregn epicentral afstand
                                distance_deg = locations2degrees(eq_lat, eq_lon, station.latitude, station.longitude)
                                distance_km, _, _ = gps2dist_azimuth(eq_lat, eq_lon, station.latitude, station.longitude)
                                distance_km = distance_km / 1000.0
                                
                                # Kontroller om i optimal afstands range
                                if min_distance_km <= distance_km <= max_distance_km:
                                    # Verificer station var operationel på jordskælv tidspunkt
                                    if (station.start_date <= eq_time and 
                                        (station.end_date is None or station.end_date >= eq_time)):
                                        
                                        # Beregn teoretiske ankomsttider
                                        arrivals = self.processor.calculate_wave_arrivals(distance_deg, eq_depth)
                                        
                                        # Opret station info dictionary
                                        station_info = {
                                            'network': network.code,
                                            'station': station.code,
                                            'latitude': station.latitude,
                                            'longitude': station.longitude,
                                            'distance_deg': round(distance_deg, 2),
                                            'distance_km': round(distance_km, 0),
                                            'p_arrival': arrivals['P'],
                                            's_arrival': arrivals['S'],
                                            'surface_arrival': arrivals['Surface'],
                                            'operational_period': f"{station.start_date.strftime('%Y')} - {'nu' if station.end_date is None else station.end_date.strftime('%Y')}",
                                            'data_source': 'IRIS_INVENTORY',
                                            'network_priority': priority_networks.index(network_code)
                                        }
                                        all_stations.append(station_info)
                            except Exception:
                                continue  # Skip problematiske stationer
                                
                except Exception as network_error:
                    continue  # Prøv næste netværk
            
            # Sortér efter netværks prioritet, derefter afstand
            all_stations.sort(key=lambda x: (x['network_priority'], x['distance_km']))
            
            # Vælg bedste stationer med geografisk distribution
            selected_stations = self._select_distributed_stations(all_stations, target_stations)
            
            if len(selected_stations) >= target_stations:
                progress_placeholder.success(f"✅ Fandt {len(selected_stations)} analyse-klar stationer")
                return selected_stations
            else:
                progress_placeholder.warning(f"⚠️ Kun {len(selected_stations)} analyse-klar stationer fundet - bruger fallback...")
                
                # Fallback med relaxed kriterier
                fallback_stations = self._fallback_station_list_optimized(earthquake, min_distance_km * 0.7, max_distance_km * 1.3, target_stations)
                progress_placeholder.info(f"✅ Bruger {len(fallback_stations)} stationer (inkl. fallback)")
                return fallback_stations
            
        except Exception as e:
            progress_placeholder.warning(f"⚠️ IRIS søgning fejl: {e} - bruger fallback...")
            return self._fallback_station_list_optimized(earthquake, min_distance_km, max_distance_km, target_stations)
    
    def _select_distributed_stations(self, stations, target_count):
        """
        Intelligent station udvælgelse for optimal geografisk distribution.
        
        Implementerer algoritme der maksimerer azimuthal coverage omkring
        jordskælv epicentrum. Dette forbedrer analyse kvalitet ved at give
        forskellige perspektiver på seismisk bølge udbredelse.
        
        Args:
            stations (list): Kandidat stationer sorteret efter prioritet
            target_count (int): Ønsket antal stationer
            
        Returns:
            list: Optimalt distribuerede stationer
            
        Algorithm:
            1. Tag altid nærmeste station først (højeste SNR)
            2. For hver yderligere station:
               - Beregn azimuthal separation fra allerede valgte
               - Score baseret på afstand kvalitet + separation
               - Vælg station med højeste total score
            3. Gentag indtil target antal nået
            
        Scoring:
            - distance_score: Favoriser ~1500 km (optimal teleseismisk)
            - separation_score: Favoriser stor azimuthal separation
            - total_score: 30% afstand + 70% separation
            
        Example:
            distributed = manager._select_distributed_stations(candidates, 4)
        """
        if len(stations) <= target_count:
            return stations
        
        selected = []
        remaining = stations.copy()
        
        # Tag altid den nærmeste station først (bedste SNR)
        selected.append(remaining.pop(0))
        
        # Vælg resterende stationer for maksimal azimuthal coverage
        while len(selected) < target_count and remaining:
            best_station = None
            best_score = -1
            
            for i, candidate in enumerate(remaining):
                # Beregn azimuthal separation fra allerede valgte stationer
                min_separation = float('inf')
                for selected_station in selected:
                    # Simpel azimuthal forskel (kunne forbedres med sfærisk geometri)
                    lat_diff = abs(candidate['latitude'] - selected_station['latitude'])
                    lon_diff = abs(candidate['longitude'] - selected_station['longitude'])
                    separation = (lat_diff**2 + lon_diff**2)**0.5
                    min_separation = min(min_separation, separation)
                
                # Score baseret på afstand kvalitet og geografisk separation
                distance_score = 1.0 / (1.0 + abs(candidate['distance_km'] - 1500) / 1000.0)  # Foretrækker ~1500km
                separation_score = min_separation
                total_score = distance_score * 0.3 + separation_score * 0.7  # Vægt separation højest
                
                if total_score > best_score:
                    best_score = total_score
                    best_station = i
            
            # Tilføj bedst scorende station
            if best_station is not None:
                selected.append(remaining.pop(best_station))
            else:
                break  # Ingen flere kandidater
        
        return selected
 
    def _fallback_station_list_optimized(self, earthquake, min_distance_km, max_distance_km, target_stations):
        """
        UDVIDET fallback til kurateret liste af analyse-klar stationer.
        
        Bruges når IRIS inventory søgning fejler eller finder utilstrækkelige stationer.
        Baseret på hånd-kurateret liste af pålidelige globale stationer med
        kendt høj data kvalitet og tilgængelighed.
        
        Args:
            earthquake (dict): Jordskælv metadata
            min_distance_km (float): Minimum afstand
            max_distance_km (float): Maksimum afstand
            target_stations (int): Ønsket antal stationer
            
        Returns:
            list: Fallback stationer i afstands range
            
        Note:
            Udvidet liste med 80+ stationer for bedre geografisk dækning.
            Fokuserer på IU/II GSN, G GEOSCOPE, GE GEOFON og pålidelige regionale netværk.
        """
        eq_lat = earthquake['latitude']
        eq_lon = earthquake['longitude']
        eq_depth = earthquake['depth_km']
        
        # MASSIVT UDVIDET liste af pålidelige analyse stationer
        # Baseret på årelang erfaring med data kvalitet og tilgængelighed
        analysis_ready_stations = [
            # ============= EUROPA - Høj kvalitets bredband stationer =============
            {'net': 'IU', 'sta': 'KONO', 'lat': 59.65, 'lon': 9.60},     # Norge - Kongsberg
            {'net': 'II', 'sta': 'BFO', 'lat': 48.33, 'lon': 8.33},      # Tyskland - Black Forest
            {'net': 'G', 'sta': 'SSB', 'lat': 45.28, 'lon': 4.54},       # Frankrig - Saint Sauveur en Rue
            {'net': 'IU', 'sta': 'KIEV', 'lat': 50.70, 'lon': 29.22},    # Ukraine - Kiev
            {'net': 'GE', 'sta': 'WLF', 'lat': 49.66, 'lon': 6.15},      # Tyskland - Walferdange
            {'net': 'G', 'sta': 'ECH', 'lat': 48.22, 'lon': 7.16},       # Frankrig - Echery
            {'net': 'GE', 'sta': 'STU', 'lat': 48.77, 'lon': 9.19},      # Tyskland - Stuttgart
            {'net': 'II', 'sta': 'ALE', 'lat': 82.50, 'lon': -62.35},    # Canada - Alert (Arktis)
            {'net': 'IU', 'sta': 'KEV', 'lat': 69.76, 'lon': 27.00},     # Finland - Kevo
            {'net': 'G', 'sta': 'UNM', 'lat': 46.79, 'lon': 8.56},       # Schweiz - Untermalingen
            {'net': 'II', 'sta': 'ESK', 'lat': 55.32, 'lon': -3.20},     # UK - Eskdalemuir
            {'net': 'G', 'sta': 'CZTB', 'lat': 50.17, 'lon': 14.55},     # Tjekkiet - Certova Tabule
            {'net': 'MN', 'sta': 'AQU', 'lat': 42.35, 'lon': 13.40},     # Italien - L'Aquila
            {'net': 'GE', 'sta': 'MORC', 'lat': 40.82, 'lon': -6.67},    # Spanien - Moraleja de Sayago
            {'net': 'HL', 'sta': 'SANT', 'lat': 36.43, 'lon': 25.46},    # Grækenland - Santorini
            
            # ============= NORDAMERIKA - GSN og regionale stationer =============
            {'net': 'IU', 'sta': 'ANMO', 'lat': 34.95, 'lon': -106.46},  # New Mexico - Albuquerque
            {'net': 'IU', 'sta': 'HRV', 'lat': 42.51, 'lon': -71.56},    # Massachusetts - Harvard
            {'net': 'IU', 'sta': 'COLA', 'lat': 64.87, 'lon': -147.86},  # Alaska - College
            {'net': 'US', 'sta': 'LRAL', 'lat': 39.88, 'lon': -77.45},   # Virginia - Lueray
            {'net': 'IU', 'sta': 'CCM', 'lat': 38.06, 'lon': -91.24},    # Missouri - Cathedral Cave
            {'net': 'IU', 'sta': 'GRFO', 'lat': 39.69, 'lon': -77.93},   # Maryland - Greenfore
            {'net': 'IU', 'sta': 'DWPF', 'lat': 28.11, 'lon': -81.44},   # Florida - Disney Wilderness
            {'net': 'IU', 'sta': 'TUC', 'lat': 32.31, 'lon': -110.78},   # Arizona - Tucson
            {'net': 'IU', 'sta': 'SSPA', 'lat': 40.64, 'lon': -77.89},   # Pennsylvania - Standing Stone
            {'net': 'IU', 'sta': 'WVT', 'lat': 36.13, 'lon': -87.83},    # Tennessee - Waverly
            {'net': 'IU', 'sta': 'JOHN', 'lat': 16.73, 'lon': -169.53},  # Johnston Island
            {'net': 'IU', 'sta': 'WAKE', 'lat': 19.28, 'lon': 166.65},   # Wake Island
            {'net': 'IU', 'sta': 'MIDW', 'lat': 28.21, 'lon': -177.37},  # Midway Island
            {'net': 'II', 'sta': 'PFO', 'lat': 33.61, 'lon': -116.46},   # Californien - Pinon Flat
            {'net': 'II', 'sta': 'BORG', 'lat': 64.75, 'lon': -21.32},   # Island - Borgarnes
            {'net': 'CN', 'sta': 'YKA', 'lat': 62.48, 'lon': -114.60},   # Canada - Yellowknife
            {'net': 'CN', 'sta': 'SCHQ', 'lat': 54.83, 'lon': -66.77},   # Canada - Schefferville
            
            # ============= ASIEN-PACIFIC - Pålidelige bredband stationer =============
            {'net': 'IU', 'sta': 'MAJO', 'lat': 36.54, 'lon': 138.20},   # Japan - Matsushiro
            {'net': 'IU', 'sta': 'INCN', 'lat': 37.48, 'lon': 126.62},   # Sydkorea - Incheon
            {'net': 'II', 'sta': 'KURK', 'lat': 50.71, 'lon': 78.62},    # Kasakhstan - Kurchatov
            {'net': 'IU', 'sta': 'ULN', 'lat': 47.87, 'lon': 107.05},    # Mongoliet - Ulaanbaatar
            {'net': 'IU', 'sta': 'CHTO', 'lat': 18.81, 'lon': 98.98},    # Thailand - Chiang Mai
            {'net': 'II', 'sta': 'MBAR', 'lat': -0.60, 'lon': 30.74},    # Rwanda - Mbarara
            {'net': 'II', 'sta': 'ABKT', 'lat': 37.93, 'lon': 58.12},    # Turkmenistan - Ashgabat
            {'net': 'II', 'sta': 'AAK', 'lat': 42.64, 'lon': 74.49},     # Kirgisistan - Ala Archa
            {'net': 'IU', 'sta': 'TARA', 'lat': 1.86, 'lon': 126.07},    # Indonesien - Tarawasi
            {'net': 'IU', 'sta': 'COCO', 'lat': -12.19, 'lon': 96.83},   # Cocos Islands
            {'net': 'IU', 'sta': 'TIXI', 'lat': 71.64, 'lon': 128.87},   # Rusland - Tiksi
            {'net': 'IU', 'sta': 'KRIB', 'lat': 1.33, 'lon': 172.92},    # Kiribati
            {'net': 'IU', 'sta': 'GUMO', 'lat': 13.59, 'lon': 144.87},   # Guam
            {'net': 'II', 'sta': 'UOSS', 'lat': 24.95, 'lon': 121.62},   # Taiwan - Uoss
            {'net': 'IU', 'sta': 'XMAS', 'lat': 2.04, 'lon': -157.45},   # Christmas Island
            {'net': 'IU', 'sta': 'RAO', 'lat': 46.99, 'lon': 142.69},    # Rusland - Raoul
            {'net': 'IU', 'sta': 'BILL', 'lat': 68.07, 'lon': 166.45},   # Rusland - Bilibino
            {'net': 'IU', 'sta': 'SLBS', 'lat': 23.69, 'lon': 90.40},    # Bangladesh - Srimangal
            {'net': 'II', 'sta': 'TLY', 'lat': 51.68, 'lon': 103.64},    # Rusland - Talaya
            {'net': 'II', 'sta': 'NNA', 'lat': -11.99, 'lon': -76.84},   # Peru - Nana
            
            # ============= AUSTRALIEN/OCEANIEN =============
            {'net': 'G', 'sta': 'CAN', 'lat': -35.32, 'lon': 149.00},    # Australien - Canberra
            {'net': 'IU', 'sta': 'CTAO', 'lat': -20.09, 'lon': 146.25},  # Australien - Charters Towers
            {'net': 'II', 'sta': 'WRAB', 'lat': -19.93, 'lon': 134.36},  # Australien - Warramunga
            {'net': 'IU', 'sta': 'NWAO', 'lat': -32.93, 'lon': 117.24},  # Australien - Narrogin
            {'net': 'IU', 'sta': 'TSUM', 'lat': -19.20, 'lon': 17.58},   # Namibia - Tsumeb
            {'net': 'G', 'sta': 'NOUC', 'lat': -22.10, 'lon': 166.30},   # Ny Kaledonien - Noumea
            {'net': 'II', 'sta': 'HOPE', 'lat': -54.28, 'lon': 158.95},  # Heard Island
            {'net': 'IU', 'sta': 'FUNA', 'lat': -8.53, 'lon': 179.20},   # Tuvalu - Funafuti
            {'net': 'IU', 'sta': 'HNR', 'lat': -9.44, 'lon': 159.95},    # Solomon Øer - Honiara
            {'net': 'IU', 'sta': 'PMSA', 'lat': -14.30, 'lon': -170.69}, # Samoa - Palmer
            {'net': 'IU', 'sta': 'RAR', 'lat': -21.21, 'lon': -159.77},  # Cook Øer - Rarotonga
            {'net': 'IU', 'sta': 'AFI', 'lat': -13.91, 'lon': -171.78},  # Samoa - Afiamalu
            
            # ============= SYDAMERIKA =============
            {'net': 'IU', 'sta': 'SAML', 'lat': -8.95, 'lon': -63.18},   # Brasilien - Samuel
            {'net': 'IU', 'sta': 'LPAZ', 'lat': -16.29, 'lon': -68.13},  # Bolivia - La Paz
            {'net': 'IU', 'sta': 'RCBR', 'lat': -5.82, 'lon': -35.90},   # Brasilien - Rocha
            {'net': 'IU', 'sta': 'SJG', 'lat': 18.11, 'lon': -66.15},    # Puerto Rico - San Juan
            {'net': 'II', 'sta': 'SACV', 'lat': 14.97, 'lon': -23.61},   # Cap Verde - Santiago
            {'net': 'IU', 'sta': 'TRQA', 'lat': -38.06, 'lon': -58.98},  # Argentina - Tornquist
            {'net': 'IU', 'sta': 'TEIG', 'lat': -35.00, 'lon': -69.00},  # Argentina - Teide
            {'net': 'GT', 'sta': 'PLCA', 'lat': 7.00, 'lon': -73.08},    # Colombia - Playa Rica
            {'net': 'IU', 'sta': 'SDDR', 'lat': -22.48, 'lon': -68.91},  # Chile - San Pedro de Atacama
            {'net': 'II', 'sta': 'CMLA', 'lat': -37.76, 'lon': -72.93},  # Chile - Camaleon
            
            # ============= AFRIKA/MELLEMØSTEN =============
            {'net': 'G', 'sta': 'TAM', 'lat': 22.79, 'lon': 5.53},       # Algeriet - Tamanrasset
            {'net': 'II', 'sta': 'MSEY', 'lat': -4.67, 'lon': 55.48},    # Seychellerne - Mahe
            {'net': 'II', 'sta': 'ASCN', 'lat': -7.93, 'lon': -14.36},   # Ascension Island
            {'net': 'G', 'sta': 'SANVU', 'lat': -15.45, 'lon': 167.20},  # Vanuatu - Santo
            {'net': 'IU', 'sta': 'KMBO', 'lat': -1.13, 'lon': 37.25},    # Kenya - Kilima Mbogo
            {'net': 'II', 'sta': 'LVNJ', 'lat': 45.30, 'lon': 28.80},    # Rumænien - Livani
            {'net': 'IU', 'sta': 'LSZA', 'lat': -29.88, 'lon': 30.67},   # Sydafrika - Lesotho
            {'net': 'II', 'sta': 'RPN', 'lat': -27.13, 'lon': -109.33},  # Easter Island - Rapa Nui
            {'net': 'IU', 'sta': 'DGAR', 'lat': -7.41, 'lon': 72.45},    # Diego Garcia
            {'net': 'G', 'sta': 'IVI', 'lat': 8.50, 'lon': -1.30},       # Elfenbenskysten - Ivory Coast
            
            # ============= ANTARKTIS =============
            {'net': 'IU', 'sta': 'QSPA', 'lat': -89.93, 'lon': 144.44},  # Sydpolen - Amundsen Scott
            {'net': 'IU', 'sta': 'SBA', 'lat': -77.85, 'lon': 166.76},   # Antarktis - Scott Base
            {'net': 'IU', 'sta': 'PMAC', 'lat': -64.77, 'lon': -64.05},  # Antarktis - Port Martin
            
            # ============= ØVRIGE HØJE KVALITETS STATIONER =============
            {'net': 'GE', 'sta': 'IBBN', 'lat': 52.34, 'lon': 9.67},     # Tyskland - Ibbenburen
            {'net': 'GE', 'sta': 'RGN', 'lat': 54.55, 'lon': 13.32},     # Tyskland - Ruegen
            {'net': 'GE', 'sta': 'BSEG', 'lat': 52.10, 'lon': 13.67},    # Tyskland - Bad Segeberg
            {'net': 'GE', 'sta': 'BRNL', 'lat': 53.11, 'lon': 8.81},     # Tyskland - Braunlage
            {'net': 'GE', 'sta': 'CLZ', 'lat': 51.86, 'lon': 10.10},     # Tyskland - Clausthal-Zellerfeld
            {'net': 'GE', 'sta': 'UGM', 'lat': 48.88, 'lon': 13.61},     # Tyskland - Untergünzburg
            {'net': 'GE', 'sta': 'CART', 'lat': 37.76, 'lon': -2.51},    # Spanien - Cartagena
            {'net': 'FR', 'sta': 'OGSI', 'lat': 47.28, 'lon': 5.51},     # Frankrig - Ouges
        ]
        
        stations = []
        for sta_data in analysis_ready_stations:
            try:
                # Beregn afstand til jordskælv
                distance_deg = locations2degrees(eq_lat, eq_lon, sta_data['lat'], sta_data['lon'])
                distance_km, _, _ = gps2dist_azimuth(eq_lat, eq_lon, sta_data['lat'], sta_data['lon'])
                distance_km = distance_km / 1000.0
                
                # Kontroller om i ønsket afstands range
                if min_distance_km <= distance_km <= max_distance_km:
                    # Beregn ankomsttider
                    arrivals = self.processor.calculate_wave_arrivals(distance_deg, eq_depth)
                    
                    # Opret station dictionary
                    station = {
                        'network': sta_data['net'],
                        'station': sta_data['sta'],
                        'latitude': sta_data['lat'],
                        'longitude': sta_data['lon'],
                        'distance_deg': round(distance_deg, 2),
                        'distance_km': round(distance_km, 0),
                        'p_arrival': arrivals['P'],
                        's_arrival': arrivals['S'],
                        'surface_arrival': arrivals['Surface'],
                        'data_source': 'ANALYSIS_READY_FALLBACK'
                    }
                    stations.append(station)
            except:
                continue  # Skip problematiske stationer
        
        # Sortér efter afstand og anvend geografisk distribution
        stations.sort(key=lambda x: x['distance_km'])
        
        # Anvend samme distributions algoritme som til IRIS data
        selected = self._select_distributed_stations(stations, target_stations)
        
        return selected[:target_stations]

    def download_waveform_data(self, earthquake, station):
        """
        Clean version der IKKE viser UI elementer - returnerer kun data eller None.
        Alle UI elementer håndteres i calling function.
        """
        if not self.client:
            return None
        
        try:
            # Hent præcis jordskælv tidspunkt fra ObsPy event
            eq_time = earthquake['obspy_event'].preferred_origin().time
            start_time = eq_time  # Ingen offset - præcis timing
            end_time = eq_time + 1800  # 30 minutter (1800 sekunder)
            
            # Prioriteret channel liste - højeste sampling rate først
            channel_priorities = ["HH*", "BH*", "LH*", "*H*", "*N*,*E*,*Z*"]
            
            waveform = None
            used_channels = None
            
            # Prøv hver channel type i prioritets rækkefølge
            for channels in channel_priorities:
                try:
                    waveform = self.client.get_waveforms(
                        network=station['network'],
                        station=station['station'],
                        location="*",  # Wildcard til alle locations
                        channel=channels,
                        starttime=start_time,
                        endtime=end_time,
                        attach_response=True  # Kritisk for kalibrering til fysiske enheder
                    )
                    
                    if len(waveform) > 0:
                        used_channels = channels
                        break  # Stop ved første succesfulde download
                            
                except Exception:
                    continue  # Prøv næste channel type
            
            # Validér at data blev hentet
            if waveform is None or len(waveform) == 0:
                return None
            
            # TIMING VALIDERING: Tjek data start tid mod jordskælv tid
            first_trace = waveform[0]
            data_start_time = first_trace.stats.starttime
            time_offset = float(data_start_time - eq_time)
            
            # Processer waveform med timing korrektion
            processed_data = self._process_real_waveform_FIXED(
                waveform, earthquake, station, used_channels, time_offset
            )
            
            if processed_data:
                # Tilføj timing metadata til output
                processed_data['timing_offset'] = time_offset
                processed_data['data_start_utc'] = data_start_time.strftime('%Y-%m-%d %H:%M:%S')
                processed_data['earthquake_utc'] = eq_time.strftime('%Y-%m-%d %H:%M:%S')
                
                # Fysisk timing validering
                is_valid, validation_message, validation_info = self.processor.validate_earthquake_timing(
                    earthquake, station, processed_data
                )
                
                processed_data['timing_validation'] = {
                    'is_valid': is_valid,
                    'message': validation_message,
                    'info': validation_info
                }
                
                return processed_data
            else:
                return None
                    
        except Exception:
            return None


    def _process_real_waveform_FIXED(self, waveform, earthquake, station, used_channels, time_offset):
        """
        Processerer real waveform data med præcis timing korrektion.
        
        Konverterer ObsPy Stream til standardiseret format med både
        rådata (counts) og kalibreret displacement (mm). Kritisk for
        at sikre korrekt timing i alle efterfølgende analyser.
        
        Args:
            waveform: ObsPy Stream objekt
            earthquake (dict): Jordskælv metadata
            station (dict): Station metadata  
            used_channels (str): Hvilke channels blev brugt
            time_offset (float): Timing korrektion i sekunder
            
        Returns:
            dict: Processeret waveform data med timing korrektion
            
        Note:
            Processerer data i to trin:
            1. Rådata (counts) - direkte fra instrument
            2. Displacement (mm) - efter response fjernelse
            
            Timing korrektion sikrer at tid=0 svarer til jordskælv tidspunkt.
            
        Example:
            processed = manager._process_real_waveform_FIXED(stream, eq, sta, "BH*", 2.5)
        """
        try:
            # Bevar original waveform til rådata (counts)
            waveform_raw = waveform.copy()
            waveform_raw.merge(method=1, fill_value=0)  # Merge gaps med nul
            
            # Ekstrahér komponenter til rådata (instrument counts)
            components_raw = {'north': None, 'east': None, 'vertical': None}
            
            channel_info = []
            for trace in waveform_raw:
                channel = trace.stats.channel
                sampling_rate = trace.stats.sampling_rate
                channel_info.append(f"{channel}")
                
                # Standard seismologisk orientering kodning
                if channel.endswith('N') or channel.endswith('1'):  # Nord
                    components_raw['north'] = trace
                elif channel.endswith('E') or channel.endswith('2'):  # Øst
                    components_raw['east'] = trace
                elif channel.endswith('Z') or channel.endswith('3'):  # Vertikal
                    components_raw['vertical'] = trace
            
            # Find tilgængelige komponenter og reference trace
            available_components = [k for k, v in components_raw.items() if v is not None]
            
            if len(available_components) == 0:
                return None
            
            reference_trace = next(v for v in components_raw.values() if v is not None)
            original_times = reference_trace.times()  # Tid array i sekunder
            sampling_rate = reference_trace.stats.sampling_rate
            
            # KRITISK FIX: Juster tider med timing offset
            # Dette sikrer at tid=0 svarer til jordskælv tidspunkt
            corrected_times = original_times + time_offset
            
            # Rådata (counts) - før enhver processering
            north_raw = components_raw['north'].data if components_raw['north'] else np.zeros(len(corrected_times))
            east_raw = components_raw['east'].data if components_raw['east'] else np.zeros(len(corrected_times))
            vertical_raw = components_raw['vertical'].data if components_raw['vertical'] else np.zeros(len(corrected_times))
            
            # Opret displacement data ved at fjerne instrument response
            waveform_for_displacement = waveform.copy()
            waveform_for_displacement.remove_response(output="DISP")  # Konverter til displacement
            waveform_for_displacement.merge(method=1, fill_value=0)
            
            # Ekstrahér displacement komponenter
            components_displacement = {'north': None, 'east': None, 'vertical': None}
            
            for trace in waveform_for_displacement:
                channel = trace.stats.channel
                if channel.endswith('N') or channel.endswith('1'):
                    components_displacement['north'] = trace
                elif channel.endswith('E') or channel.endswith('2'):
                    components_displacement['east'] = trace
                elif channel.endswith('Z') or channel.endswith('3'):
                    components_displacement['vertical'] = trace
            
            # Displacement data konverteret til mm (fra meters)
            north_mm = (components_displacement['north'].data * 1000) if components_displacement['north'] else np.zeros(len(corrected_times))
            east_mm = (components_displacement['east'].data * 1000) if components_displacement['east'] else np.zeros(len(corrected_times))
            vertical_mm = (components_displacement['vertical'].data * 1000) if components_displacement['vertical'] else np.zeros(len(corrected_times))
            
            # Returner komplet data struktur
            return {
                'time': corrected_times,  # Tid med korrektion
                'sampling_rate': sampling_rate,
                'data_source': f'IRIS_{used_channels or "UNK"}',
                'available_components': available_components,
                'channel_info': channel_info,
                'timing_offset': time_offset,
                'timing_corrected': True,
                'raw_data': {  # Original instrument counts
                    'north': north_raw,
                    'east': east_raw,
                    'vertical': vertical_raw
                },
                'displacement_data': {  # Kalibreret displacement i mm
                    'north': north_mm,
                    'east': east_mm,
                    'vertical': vertical_mm
                }
            }
            
        except Exception as e:
            st.error(f"❌ Dataprocessering fejl: {e}")
            return None
    
    def export_to_excel(self, earthquake, station, waveform_data, ms_magnitude, ms_explanation):
        """
        Eksporterer komplet analyse til Excel format med metadata og tidsserier.
        
        Opretter professionel Excel rapport med to sheets:
        1. Metadata: Komplet information om jordskælv, station og analyse
        2. Time_Series_Data: Downsampled data til Excel effektivitet
        
        Args:
            earthquake (dict): Jordskælv metadata
            station (dict): Station metadata
            waveform_data (dict): Processeret waveform data
            ms_magnitude (float): Beregnet Ms magnitude
            ms_explanation (str): Ms beregnings forklaring
            
        Returns:
            bytes or None: Excel fil som byte array eller None ved fejl
            
        Note:
            Data downsamples til 2 Hz (0.5s interval) for Excel effektivitet
            mens original high-rate data bevares i applikationen.
            
        Features:
            - Komplet metadata preserve
            - Timing information og validering
            - Både rådata og displacement
            - Professionel formatering
            - Ready-to-use for videre analyse
            
        Example:
            excel_data = manager.export_to_excel(eq, sta, data, 7.2, explanation)
            if excel_data:
                with open('analysis.xlsx', 'wb') as f:
                    f.write(excel_data)
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
            metadata_sheet.write(row, 1, earthquake['latitude'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Earthquake Longitude')
            metadata_sheet.write(row, 1, earthquake['longitude'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Earthquake Depth (km)')
            metadata_sheet.write(row, 1, earthquake['depth_km'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Earthquake Time')
            metadata_sheet.write(row, 1, earthquake['time'].strftime('%Y-%m-%d %H:%M:%S'))
            row += 1
            
            # Station metadata
            metadata_sheet.write(row, 0, 'Station Network')
            metadata_sheet.write(row, 1, station['network'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Station Code')
            metadata_sheet.write(row, 1, station['station'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Station Latitude')
            metadata_sheet.write(row, 1, station['latitude'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Station Longitude')
            metadata_sheet.write(row, 1, station['longitude'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Distance (km)')
            metadata_sheet.write(row, 1, station['distance_km'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Distance (degrees)')
            metadata_sheet.write(row, 1, station['distance_deg'])
            row += 1
            
            # Ankomsttider
            metadata_sheet.write(row, 0, 'P Arrival (s)')
            metadata_sheet.write(row, 1, station.get('p_arrival', 'N/A'))
            row += 1
            
            metadata_sheet.write(row, 0, 'S Arrival (s)')
            metadata_sheet.write(row, 1, station.get('s_arrival', 'N/A'))
            row += 1
            
            metadata_sheet.write(row, 0, 'Surface Arrival (s)')
            metadata_sheet.write(row, 1, station.get('surface_arrival', 'N/A'))
            row += 1
            
            # Timing information
            if 'timing_offset' in waveform_data:
                metadata_sheet.write(row, 0, 'Timing Offset (s)')
                metadata_sheet.write(row, 1, waveform_data['timing_offset'])
                row += 1
            
            if 'timing_validation' in waveform_data:
                validation = waveform_data['timing_validation']
                metadata_sheet.write(row, 0, 'Timing Valid')
                metadata_sheet.write(row, 1, 'Yes' if validation['is_valid'] else 'No')
                row += 1
                
                if validation['info']:
                    metadata_sheet.write(row, 0, 'P-wave Velocity (km/s)')
                    metadata_sheet.write(row, 1, validation['info']['implicit_velocity'])
                    row += 1
            
            # Ms magnitude
            if ms_magnitude:
                metadata_sheet.write(row, 0, 'Ms Magnitude')
                metadata_sheet.write(row, 1, ms_magnitude)
                row += 1
            
            # Data parametre
            metadata_sheet.write(row, 0, 'Sampling Rate (Hz)')
            metadata_sheet.write(row, 1, waveform_data['sampling_rate'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Data Source')
            metadata_sheet.write(row, 1, waveform_data['data_source'])
            row += 1
            
            metadata_sheet.write(row, 0, 'Available Components')
            metadata_sheet.write(row, 1, ', '.join(waveform_data['available_components']))
            
            # Downsample data til ~0.5 sekund intervaller (2 Hz) - KUN TIL EXCEL
            # Dette reducerer fil størrelse betydeligt uden at påvirke analyse kvalitet
            times = waveform_data['time']
            original_rate = waveform_data['sampling_rate']
            target_rate = 2.0  # 2 Hz = 0.5 sekund intervaller
            downsample_factor = max(1, int(original_rate / target_rate))
            
            # Tidsserier data sheet
            timeseries_sheet = workbook.add_worksheet('Time_Series_Data')
            
            # Headers til tidsserier
            timeseries_sheet.write('A1', 'Time (s)', header_format)
            timeseries_sheet.write('B1', 'North_Raw (counts)', header_format)
            timeseries_sheet.write('C1', 'East_Raw (counts)', header_format)
            timeseries_sheet.write('D1', 'Vertical_Raw (counts)', header_format)
            timeseries_sheet.write('E1', 'North_Disp (mm)', header_format)
            timeseries_sheet.write('F1', 'East_Disp (mm)', header_format)
            timeseries_sheet.write('G1', 'Vertical_Disp (mm)', header_format)
            
            # Downsample og skriv data - KUN TIL EXCEL (original data uændret)
            downsampled_times = times[::downsample_factor]
            
            for i, t in enumerate(downsampled_times):
                idx = i * downsample_factor
                if idx < len(times):
                    try:
                        timeseries_sheet.write(i + 1, 0, float(t))
                        timeseries_sheet.write(i + 1, 1, float(waveform_data['raw_data']['north'][idx]))
                        timeseries_sheet.write(i + 1, 2, float(waveform_data['raw_data']['east'][idx]))
                        timeseries_sheet.write(i + 1, 3, float(waveform_data['raw_data']['vertical'][idx]))
                        timeseries_sheet.write(i + 1, 4, float(waveform_data['displacement_data']['north'][idx]))
                        timeseries_sheet.write(i + 1, 5, float(waveform_data['displacement_data']['east'][idx]))
                        timeseries_sheet.write(i + 1, 6, float(waveform_data['displacement_data']['vertical'][idx]))
                    except Exception:
                        continue  # Skip problematiske data punkter
            
            # Formatering af kolonner
            metadata_sheet.set_column('A:A', 25)
            metadata_sheet.set_column('B:B', 20)
            timeseries_sheet.set_column('A:G', 15)
            
            workbook.close()
            output.seek(0)
            
            return output.getvalue()
            
        except Exception as e:
            print(f"❌ Excel export error: {e}")
            return None


    
class StreamlinedSeismicApp:
    """
    Hovedapplikation klasse der integrerer alle komponenter til samlet brugeroplevelse.
    OPTIMERET VERSION - ingen dobbelt rendering, stabile sliders, ingen kort titel.
    """
    
    def _format_time_display(self, days):
        """Helper funktion til tid formatering"""
        if days == 0:
            return "i dag"
        elif days == 1:
            return "1 dag"
        elif days <= 30:
            return f"{days} dage"
        elif days <= 365:
            months = days // 30
            return f"~{months} måneder"
        else:
            years = days // 365
            return f"~{years} år"
        

    def __init__(self):
            """Initialiserer hovedapplikation med session state og data manager."""
            self.setup_session_state()
            self.data_manager = StreamlinedDataManager()
            self.initialize_app()
                    # Sidebar med smart indhold
            with st.sidebar:
                if st.session_state.sidebar_visible:
                    # Header sektion
                    st.subheader("🌍 GEOseis")
                    st.caption("Version 3.2 - Juni 2025")
                    
                    # Beskrivelse sektion
                    with st.expander("🌍 Om programmet", expanded=True):
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">GEOseis er udviklet til naturvidenskabsundervisere på ungdoms- eller tilsvarende uddannelser. Man kan let finde, analysere og omforme seismiske data fra jordskælv så de kan bruges i undervisningen. Siden har et omfattende interaktivt analyseværktøj som skal hjælpe med at forstå og finde pædagiske eksempler til undervisningen. </p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">Udviklet af: Philip Kruse Jakobsen, pj@sg.dk</p>', unsafe_allow_html=True)
                        
                    # Quick start sektion
                    with st.expander("🚀 Quick Start", expanded=True):
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">1. Justér filtre → Magnitude range, dybde og årstal</p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">2. Klik jordskælv → På det interaktive kort</p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">3. Vælg station → Fra listen til højre</p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">4. Se analyse, anvend evt. filtre </p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">5. Eksporter → Download Excel fil </p>', unsafe_allow_html=True)
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">5. Der findes en brugerguide i analyseafsnittet </p>', unsafe_allow_html=True)
                else:
                    # Helt tom sidebar når collapsed
                    pass

    def setup_session_state(self):
        """Opsætter Streamlit session state med standard værdier."""
        # Standard filter indstillinger
        if 'magnitude_range' not in st.session_state:
            st.session_state.magnitude_range = (6.5, 9.0)
        
        if 'year_range' not in st.session_state:
            current_year = datetime.now().year
            st.session_state.year_range = (2020, current_year)
            
        # Dybde range filter (1-750 km som default)
        if 'depth_range' not in st.session_state:
            st.session_state.depth_range = (1, 750)
        
        # Max antal jordskælv (standard 25)
        if 'max_earthquakes' not in st.session_state:
            st.session_state.max_earthquakes = 25
        
        # Data state
        if 'earthquake_df' not in st.session_state:
            st.session_state.earthquake_df = pd.DataFrame()
        
        if 'data_loaded' not in st.session_state:
            st.session_state.data_loaded = False
        
        # Selection state
        if 'selected_earthquake' not in st.session_state:
            st.session_state.selected_earthquake = None
        
        if 'selected_station' not in st.session_state:
            st.session_state.selected_station = None
        
        # UI state
        if 'show_stations' not in st.session_state:
            st.session_state.show_stations = False
        
        if 'show_analysis' not in st.session_state:
            st.session_state.show_analysis = False
        
        # Data cache
        if 'station_list' not in st.session_state:
            st.session_state.station_list = []
        
        if 'waveform_data' not in st.session_state:
            st.session_state.waveform_data = None
        
        if 'analysis_results' not in st.session_state:
            st.session_state.analysis_results = None

        # Initialize sidebar state
        if 'sidebar_visible' not in st.session_state:
            st.session_state.sidebar_visible = True
        
        # Component visibility for waveform plots
        if 'component_visibility' not in st.session_state:
            st.session_state.component_visibility = {
                'north': True,
                'east': True, 
                'vertical': True
            }

    def initialize_app(self):
        """Initialiserer applikation med header og initial data loading."""
        
        st.markdown('<div id="map-section" style="scroll-margin-top: 0px;"></div>', unsafe_allow_html=True)
        st.markdown("## 🌍 GEOseis")
        st.markdown("**Overskuelig seismisk analyse med Excel-eksport til undervisningen**")
        
        # KRITISK FIX: Tilføj slider_initialized flag
        if 'sliders_initialized' not in st.session_state:
            st.session_state.sliders_initialized = False
        
            
        # KRITISK FIX: Kun load data ved første besøg eller hvis sliders er initialiseret
        if not st.session_state.data_loaded and st.session_state.sliders_initialized:
            with st.spinner("🔍 Indlæser jordskælv..."):
                self.load_initial_data()
        elif not st.session_state.data_loaded and not st.session_state.sliders_initialized:
            # Første gang - load data uden at vente på sliders
            with st.spinner("🔍 Indlæser jordskælv..."):
                self.load_initial_data()
                st.session_state.sliders_initialized = True


    def load_initial_data(self):
        """Henter initial jordskælv data ved app opstart eller filter opdatering."""
        try:
            # TILFØJET: Undgå genindlæsning hvis data allerede er loadet og sliders bare ændres
            if st.session_state.data_loaded and not st.session_state.get('force_reload', False):
                return
            
            # Reset force_reload flag
            if 'force_reload' in st.session_state:
                st.session_state.force_reload = False
            
            # Hent filter værdier fra session state
            magnitude_range = st.session_state.magnitude_range
            year_range = st.session_state.year_range
            depth_range = st.session_state.depth_range
            max_count = st.session_state.max_earthquakes
            
            earthquakes = self.data_manager.fetch_latest_earthquakes(
                magnitude_range=magnitude_range,
                year_range=year_range,
                depth_range=depth_range,
                limit=max_count
            )
            
            if earthquakes:
                earthquakes_df = pd.DataFrame(earthquakes)
                st.session_state.earthquake_df = earthquakes_df
                st.session_state.data_loaded = True
            else:
                st.session_state.earthquake_df = pd.DataFrame()
                st.session_state.data_loaded = True
                    
        except Exception as e:
            st.error(f"❌ Fejl ved indlæsning af data: {str(e)}")
            st.session_state.earthquake_df = pd.DataFrame()
            st.session_state.data_loaded = True

    def get_earthquake_color_and_size(self, magnitude):
        """Bestemmer farve og størrelse for jordskælv markører baseret på magnitude."""
        if magnitude >= 8.0:
            return 'purple', 15  # ÆNDRET: Lilla for de største jordskælv
        elif magnitude >= 7.5:
            return 'darkred', 12
        elif magnitude >= 7.0:
            return 'red', 10
        elif magnitude >= 6.5:
            return 'orange', 8
        elif magnitude >= 6.0:
            return 'yellow', 6
        elif magnitude >= 5.0:
            return 'lightgreen', 5
        else:
            return 'gray', 4  # Fallback for M < 5.0 (selvom de ikke forekommer)
    
    def create_optimized_map(self, earthquakes_df, stations=None):
        """
        Opretter optimeret Folium kort med ren og simpel zoom logik.
        RETTET VERSION - Med korrekte golden border station markører og rød selektion.
        """
        if earthquakes_df.empty:
            return None
        
        # Check om vi skal vise stationer view eller global view
        selected_eq = st.session_state.get('selected_earthquake')
        show_stations = st.session_state.get('show_stations', False)
        
        if stations and show_stations and selected_eq:
            # STATIONS VIEW: Zoom ind på valgt jordskælv og stationer
            eq_lat, eq_lon = selected_eq['latitude'], selected_eq['longitude']
            station_lats = [s['latitude'] for s in stations]
            station_lons = [s['longitude'] for s in stations]
            
            # Find bounds for jordskælv + stationer
            all_lats = [eq_lat] + station_lats
            all_lons = [eq_lon] + station_lons
            
            lat_min, lat_max = min(all_lats), max(all_lats)
            lon_min, lon_max = min(all_lons), max(all_lons)
            
            # Simpel center beregning
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            
            # Opret kort med fokuseret view
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=6,
                tiles='Esri_WorldImagery',
                attr=' ',
                scrollWheelZoom=True,
                doubleClickZoom=True,
                dragging=True,
                zoomControl=False
            )
            
            # Simpel bounds beregning - kun lidt ekstra plads
            lat_padding = max((lat_max - lat_min) * 0.1, 1.0)
            lon_padding = max((lon_max - lon_min) * 0.1, 1.0)
            
            southwest = [lat_min - lat_padding, lon_min - lon_padding]
            northeast = [lat_max + lat_padding, lon_max + lon_padding]
            m.fit_bounds([southwest, northeast])
            
            # Vis kun valgt jordskælv
            display_earthquakes_df = earthquakes_df[earthquakes_df['index'] == selected_eq['index']].copy()
            
        else:
            # GLOBAL VIEW: Vis hele jorden med Asien i centrum
            # Fast global view - ingen kompliceret beregning
            m = folium.Map(
                location=[10, 70],  # Asien centrum: 30°N, 100°E
                zoom_start=2,
                tiles='Esri_WorldImagery',
                attr=' ',
                scrollWheelZoom=True,
                doubleClickZoom=True,
                dragging=True,
                zoomControl=False,
                world_copy_jump=True  # Bedre global navigation
            )
            
            # Ingen fit_bounds - lad kortet vise sig naturligt
            display_earthquakes_df = earthquakes_df.copy()
        
        # Tilføj jordskælv markører
        for idx, eq in display_earthquakes_df.iterrows():
            color, radius = self.get_earthquake_color_and_size(eq['magnitude'])
            
            # Stjerne for valgt jordskælv
            if (selected_eq and selected_eq['index'] == eq['index']):
                folium.Marker(
                    location=[eq['latitude'], eq['longitude']],
                    tooltip=f"⭐ VALGT: M{eq['magnitude']:.1f} - {eq['time'].strftime('%d %b %Y')}",
                    popup=f"⭐ VALGT M {eq['magnitude']:.1f}<br>{eq['time'].strftime('%d %b %Y')}",
                    icon=folium.DivIcon(
                        html='<div style="font-size: 20px; text-align: center;">⭐</div>',
                        icon_size=(20, 20),
                        icon_anchor=(10, 10)
                    )
                ).add_to(m)
            else:
                # Normal cirkel markør
                folium.CircleMarker(
                    location=[eq['latitude'], eq['longitude']],
                    radius=radius,
                    tooltip=f"M{eq['magnitude']:.1f} - {eq['time'].strftime('%d %b %Y')} (Klik for stationer)",
                    color='black',
                    opacity=0.6,
                    fillColor=color,
                    fillOpacity=0.8,
                    weight=1
                ).add_to(m)
        
        # RETTET: Tilføj stationer med golden border og rød selektion
        if stations and show_stations:
            for i, station in enumerate(stations):
                station_id = i + 1
                
                # Bestem farver baseret på selektion
                if (st.session_state.get('selected_station') and 
                    st.session_state.selected_station['station'] == station['station']):
                    # RØD for valgt station
                    triangle_color = 'red'
                    text_color = 'white'
                else:
                    # BLÅ for ikke-valgte stationer
                    triangle_color = 'blue'
                    text_color = 'white'
                
                # RETTET: Custom HTML til trekant med GOLDEN kant og centreret nummer
                triangle_html = f'''
                <div style="
                    width: 0; 
                    height: 0; 
                    border-left: 14px solid transparent;
                    border-right: 14px solid transparent;
                    border-bottom: 22px solid gold;
                    position: relative;
                    cursor: pointer;
                    filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
                ">
                    <div style="
                        width: 0; 
                        height: 0; 
                        border-left: 11px solid transparent;
                        border-right: 11px solid transparent;
                        border-bottom: 18px solid {triangle_color};
                        position: absolute;
                        top: 2px;
                        left: -11px;
                        cursor: pointer;
                    ">
                        <div style="
                            position: absolute;
                            top: 6px;
                            left: -5.5px;
                            width: 11px;
                            height: 12px;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            color: {text_color};
                            font-weight: bold;
                            font-size: 10px;
                            text-align: center;
                            text-shadow: 1px 1px 2px rgba(0,0,0,0.7);
                            line-height: 1;
                        ">{station_id}</div>
                    </div>
                </div>
                '''
                
                # Tooltip tekst med station info
                source_info = station.get('data_source', 'UNKNOWN')
                tooltip_text = f"{station['network']}.{station['station']} ({station['distance_km']:.0f} km)<br> - klik på listen til højre -"
                if 'IRIS_INVENTORY' in source_info:
                    tooltip_text += " ✅ IRIS Verified"
                elif 'FALLBACK' in source_info:
                    tooltip_text += " ⚠️ Fallback List"
                
                # Tilføj custom marker med korrekt størrelse
                folium.Marker(
                    location=[station['latitude'], station['longitude']],
                    icon=folium.DivIcon(
                        html=triangle_html,
                        icon_size=(28, 24),
                        icon_anchor=(14, 24)
                    ),
                    tooltip=tooltip_text
                ).add_to(m)
        # TILFØJET: Signaturforklaring (legend) med opdaterede farver
        legend_html = '''
        <div style="position: fixed; 
                    top: 80px; left: 10px; width: 105px; height: 175px; 
                    background-color: rgba(255, 255, 255, 0.9);
                    border: 2px solid grey; z-index: 9999; font-size: 12px;
                    border-radius: 5px; padding: 10px;
                    ">
        <p style="margin: 0; font-weight: bold; text-align: center;">Magnitude</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:purple"></i> M ≥ 8.0</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:darkred"></i> M 7.5-7.9</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:red"></i> M 7.0-7.4</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:orange"></i> M 6.5-6.9</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:yellow"></i> M 6.0-6.4</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:lightgreen"></i> M 5.0-5.9</p>
        <p style="margin: 5px 0 0 0; font-size: 12px; color: #666;">⭐ = Valgt</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        return m
    def process_earthquake_click(self, clicked_lat, clicked_lon, earthquakes_df):
        """Fixed version med bedre afstands tolerance."""
        try:
            print(f"DEBUG: Processing earthquake click at {clicked_lat}, {clicked_lon}")
            
            closest_eq = None
            min_distance = float('inf')
            
            # Find nærmeste jordskælv
            for _, eq in earthquakes_df.iterrows():
                distance = ((eq['latitude'] - clicked_lat)**2 + (eq['longitude'] - clicked_lon)**2)**0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_eq = eq.to_dict()
            
            print(f"DEBUG: Closest earthquake: {closest_eq['magnitude'] if closest_eq else 'None'}, distance: {min_distance}")
            
            # ØGET TOLERANCE: Fra 3.0 til 10.0 grader
            if closest_eq and min_distance < 10.0:  # ÆNDRET fra 3.0
                current_eq = st.session_state.get('selected_earthquake')
                
                print(f"DEBUG: Current selected: {current_eq['index'] if current_eq else 'None'}")
                print(f"DEBUG: New earthquake: {closest_eq['index']}")
                
                if not current_eq or current_eq['index'] != closest_eq['index']:
                    print("DEBUG: NEW EARTHQUAKE SELECTED - SETTING STATE")
                    
                    # Explicit state reset
                    st.session_state.selected_earthquake = closest_eq
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.session_state.show_analysis = False
                    st.session_state.show_stations = False
                    st.session_state.station_list = []
                    
                    # Set pending flag
                    st.session_state.pending_station_search = True
                    
                    print(f"DEBUG: State set - pending_station_search: {st.session_state.pending_station_search}")
                    return True
                else:
                    print("DEBUG: Same earthquake clicked - toggling stations")
                    if not st.session_state.get('show_stations', False):
                        st.session_state.show_stations = True
                    return True
            else:
                print(f"DEBUG: No earthquake found in range (distance: {min_distance}, limit: 10.0)")
            
            return False
            
        except Exception as e:
            print(f"DEBUG: Exception in process_earthquake_click: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def handle_earthquake_click(self, map_data, earthquakes_df):
        """Håndterer jordskælv klik detektion fra Folium kort - OPTIMERET VERSION."""
        try:
            if not map_data or not map_data.get("last_clicked"):
                return False
            
            last_clicked = map_data["last_clicked"]
            if not isinstance(last_clicked, dict) or "lat" not in last_clicked or "lng" not in last_clicked:
                return False
                
            clicked_lat = last_clicked["lat"]
            clicked_lon = last_clicked["lng"]
            
            return self.process_earthquake_click(clicked_lat, clicked_lon, earthquakes_df)
            
        except Exception:
            return False
  
    def _process_map_clicks(self, map_data, df):
        """Forbedret klik håndtering med bedre debugging."""
        if not map_data:
            return False
        
        # DEBUG: Log hvad vi modtager
        print(f"DEBUG: Map data keys: {map_data.keys()}")
        if map_data.get("last_clicked"):
            print(f"DEBUG: last_clicked: {map_data['last_clicked']}")
        if map_data.get("last_object_clicked"):
            print(f"DEBUG: last_object_clicked: {map_data['last_object_clicked']}")
        
        click_detected = False
        clicked_lat = None
        clicked_lon = None
        
        # Prioriteret klik håndtering - prøv object først, så general
        if map_data.get("last_object_clicked"):
            try:
                clicked_obj = map_data["last_object_clicked"]
                if clicked_obj and isinstance(clicked_obj, dict):
                    if "lat" in clicked_obj and "lng" in clicked_obj:
                        clicked_lat = clicked_obj["lat"]
                        clicked_lon = clicked_obj["lng"]
                        print(f"DEBUG: Object click detected at {clicked_lat}, {clicked_lon}")
            except Exception as e:
                print(f"DEBUG: Object click failed: {e}")
        
        # Fallback til general click
        if clicked_lat is None and map_data.get("last_clicked"):
            try:
                last_clicked = map_data["last_clicked"]
                if isinstance(last_clicked, dict) and "lat" in last_clicked and "lng" in last_clicked:
                    clicked_lat = last_clicked["lat"]
                    clicked_lon = last_clicked["lng"]
                    print(f"DEBUG: General click detected at {clicked_lat}, {clicked_lon}")
            except Exception as e:
                print(f"DEBUG: General click failed: {e}")
        
        # Processer klik hvis vi har koordinater
        if clicked_lat is not None and clicked_lon is not None:
            print(f"DEBUG: Processing click at {clicked_lat}, {clicked_lon}")
            
            # CHECK: Er dette et nyt klik eller gentagelse?
            last_processed_click = st.session_state.get('last_processed_click')
            current_click = (round(clicked_lat, 6), round(clicked_lon, 6))
            
            if last_processed_click == current_click:
                print("DEBUG: Duplicate click detected - ignoring")
                return False
            
            # Gem dette klik som processed
            st.session_state.last_processed_click = current_click
            
            click_detected = self.process_earthquake_click(clicked_lat, clicked_lon, df)
            print(f"DEBUG: Click processing result: {click_detected}")
        
        return click_detected

    def create_main_interface(self):
        """Hovedinterface med clean persistent fejlhåndtering."""
        df = st.session_state.earthquake_df
        
        # FØRST: Vis eventuelle persistent fejlbeskeder
        if 'station_error_message' in st.session_state:
            error_data = st.session_state.station_error_message
            st.error(f"❌ {error_data['message']}")
            
            # Vis detaljer hvis tilgængelig
            if error_data.get('details'):
                with st.expander("📋 Se detaljer om problemet"):
                    for detail in error_data['details']:
                        st.write(f"• {detail}")
            
            # Vis forslag
            if error_data.get('suggestions'):
                st.info("💡 **Hvad kan du gøre:**")
                for suggestion in error_data['suggestions']:
                    st.write(f"• {suggestion}")
            
            # Ryd besked knap
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("✕ Luk besked", key="clear_error"):
                    del st.session_state.station_error_message
                    st.rerun()
        
        # TRIN 2: Check om vi skal søge stationer EFTER zoom
        if st.session_state.get('pending_station_search', False):
            selected_eq = st.session_state.get('selected_earthquake')
            if selected_eq:
                # Søg stationer nu hvor kortet er zoomet
                with st.spinner(f"Søger stationer for M{selected_eq['magnitude']:.1f}..."):
                    try:
                        new_stations = self.data_manager.find_stations_for_earthquake(selected_eq)
                        if new_stations:
                            st.session_state.station_list = new_stations
                            st.session_state.show_stations = True
                        else:
                            st.session_state.station_list = []
                            st.session_state.show_stations = False
                    except:
                        st.session_state.station_list = []
                        st.session_state.show_stations = False
                
                # Fjern pending flag og trigger rerun
                st.session_state.pending_station_search = False
                st.rerun()
        
        # Layout
        col1, col2 = st.columns([3, 1])
        
        with col1:
            # KORT SEKTION
            if df.empty:
                # Vis hjælpsom information ved tomme resultater
                magnitude_range = st.session_state.magnitude_range
                year_range = st.session_state.year_range
                depth_range = st.session_state.depth_range
                
                min_mag, max_mag = magnitude_range
                start_year, end_year = year_range
                min_depth, max_depth = depth_range
                
                st.warning("🔍 Ingen jordskælv fundet med disse kriterier")
                st.info(f"**Søgte:** M{min_mag:.1f}-{max_mag:.1f}, {start_year}-{end_year}, {min_depth}-{max_depth}km dybde")
                
                # Intelligente forslag baseret på kriterier
                suggestions = []
                if min_mag > 7.0:
                    suggestions.append("💡 Prøv lavere magnitude: Store jordskælv (M>7) er sjældne")
                if max_depth < 100:
                    suggestions.append("💡 Udvid dybde range: Mange jordskælv er dybere end 100km")
                if (end_year - start_year) < 5:
                    suggestions.append("💡 Udvid tidsperiode: Prøv flere år for bedre resultater")
                
                if suggestions:
                    for suggestion in suggestions[:2]:
                        st.caption(suggestion)
                
                # Hurtige løsninger
                st.markdown("**⚡ Hurtige løsninger:**")
                col_a, col_b, col_c = st.columns(3)
                
                with col_a:
                    if st.button("🌍 Populære", use_container_width=True, key="quick_popular"):
                        st.session_state.magnitude_range = (6.0, 9.0)
                        st.session_state.year_range = (2020, 2025)
                        st.session_state.depth_range = (1, 200)
                        st.session_state.max_earthquakes = 50
                        st.session_state.force_reload = True  # TILFØJET
                        with st.spinner("🔍 Søger populære jordskælv..."):
                            self.load_initial_data()
                        st.rerun()
                
                with col_b:
                    if st.button("🔥 Store (M7+)", use_container_width=True, key="quick_large"):
                        st.session_state.magnitude_range = (7.0, 9.0)
                        st.session_state.year_range = (2000, 2025)
                        st.session_state.depth_range = (1, 700)
                        st.session_state.max_earthquakes = 100
                        st.session_state.force_reload = True  # TILFØJET
                        with st.spinner("🔍 Søger store jordskælv..."):
                            self.load_initial_data()
                        st.rerun()
                
                with col_c:
                    if st.button("🏔️ Overfladiske", use_container_width=True, key="quick_shallow"):
                        st.session_state.magnitude_range = (6.0, 8.0)
                        st.session_state.year_range = (2015, 2025)
                        st.session_state.depth_range = (1, 50)
                        st.session_state.max_earthquakes = 75
                        st.session_state.force_reload = True  # TILFØJET
                        with st.spinner("🔍 Søger overfladiske jordskælv..."):
                            self.load_initial_data()
                        st.rerun()
                        
                return
            else:
                # Vis kort når der ER data
                stations = st.session_state.get('station_list', []) if st.session_state.get('show_stations', False) else []
                earthquake_map = self.create_optimized_map(df, stations)
                
                if earthquake_map is not None:
                    # Brug fast key for stabilitet
                    map_key = "earthquake_map"
                    
                    map_data = st_folium(
                        earthquake_map, 
                        width=950, 
                        height=650,
                        returned_objects=["last_object_clicked", "last_clicked"],
                        key=map_key
                    )
                    
                    # Klik håndtering
                    if map_data and (map_data.get("last_clicked") or map_data.get("last_object_clicked")):
                        click_detected = self._process_map_clicks(map_data, df)
                        if click_detected:
                            st.rerun()
        
        with col2:
            # HØJRE SIDE MENU
            
            # Filter menu
            has_selected_earthquake = st.session_state.get('selected_earthquake') is not None
            shows_stations = st.session_state.get('show_stations', False)
            menu_expanded = not (has_selected_earthquake and shows_stations)
            
            if has_selected_earthquake and shows_stations:
                header_text = "SØG EFTER JORDSKÆLV"
            else:
                header_text = "**← Klik på et jordskælv på kortet**"
            
            with st.expander(header_text, expanded=menu_expanded):
                # CSS for slider farver
                st.markdown("""
                <style>
                div[data-testid="stSlider"]:has(label:contains("Magnitude")) .stSlider > div > div > div > div {
                    background-color: #1f77b4 !important;
                }
                div[data-testid="stSlider"]:has(label:contains("Årstal")) .stSlider > div > div > div > div {
                    background-color: #2ca02c !important;
                }
                div[data-testid="stSlider"]:has(label:contains("Dybde")) .stSlider > div > div > div > div {
                    background-color: #9467bd !important;
                }
                div[data-testid="stSlider"]:has(label:contains("Max antal")) .stSlider > div > div > div > div {
                    background-color: #ff7f0e !important;
                }
                </style>
                """, unsafe_allow_html=True)
                
                # FIXED SLIDERS - Tilføj on_change=None til alle
                temp_magnitude_range = st.slider(
                    "Magnitude", 5.0, 9.0, st.session_state.magnitude_range, 0.1,
                    key="mag_range_slider_temp", 
                    help="Vælg minimum og maksimum magnitude", 
                    format="%.1f",
                    on_change=None  # TILFØJET - forhindrer auto-trigger
                )
                
                from datetime import datetime
                current_year = datetime.now().year
                temp_year_range = st.slider(
                    "Årstal", 1990, current_year, st.session_state.year_range, 1,
                    key="year_range_slider_temp", 
                    help=f"Vælg periode fra 1990 til {current_year}", 
                    format="%d",
                    on_change=None  # TILFØJET - forhindrer auto-trigger
                )
                
                temp_depth_range = st.slider(
                    "Dybde (km)", 1, 700, st.session_state.depth_range, 1,
                    key="depth_range_slider_temp", 
                    help="Vælg minimum og maksimum jordskælv dybde i km", 
                    format="%d",
                    on_change=None  # TILFØJET - forhindrer auto-trigger
                )
                
                temp_max_earthquakes = st.slider(
                    "Max antal jordskælv", 1, 500, st.session_state.get('max_earthquakes', 25), 1,
                    key="max_earthquakes_slider_temp", 
                    help="Maksimalt antal jordskælv der vises på kortet", 
                    format="%d",
                    on_change=None  # TILFØJET - forhindrer auto-trigger
                )
                
                # Check for changes
                settings_changed = (
                    temp_magnitude_range != st.session_state.magnitude_range or 
                    temp_year_range != st.session_state.year_range or
                    temp_depth_range != st.session_state.depth_range or
                    temp_max_earthquakes != st.session_state.get('max_earthquakes', 25)
                )
                
                if settings_changed:
                    st.markdown('<p style="color: #999999; font-size: 14px; margin: 2px 0;">Indstillinger ændret...</p>', unsafe_allow_html=True)
                    update_button = st.button("**Opdater**", key="update_earthquake_btn", use_container_width=True, type="primary")
                else:
                    update_button = False
                
                if update_button and settings_changed:
                    # Opdater session state
                    st.session_state.magnitude_range = temp_magnitude_range
                    st.session_state.year_range = temp_year_range
                    st.session_state.depth_range = temp_depth_range
                    st.session_state.max_earthquakes = temp_max_earthquakes
                    
                    # TILFØJET - Force reload flag
                    st.session_state.force_reload = True
                    
                    # Reset state
                    st.session_state.selected_earthquake = None
                    st.session_state.selected_station = None
                    st.session_state.show_stations = False
                    st.session_state.show_analysis = False
                    st.session_state.waveform_data = None
                    st.session_state.station_list = []
                    st.session_state.pending_station_search = False
                    
                    # Ryd eventuelle fejlbeskeder
                    if 'station_error_message' in st.session_state:
                        del st.session_state.station_error_message
                    
                    with st.spinner("🔍 Søger jordskælv..."):
                        self.load_initial_data()
                    st.rerun()

            # STATION MENU
            selected_eq = st.session_state.get('selected_earthquake')
            selected_station = st.session_state.get('selected_station')
            stations = st.session_state.get('station_list', [])
            
            if selected_eq:
                if selected_station:
                    header_text = f"VÆLG NY STATION"
                else:
                    header_text = f"VÆLG STATION"
                
                with st.expander(header_text, expanded=not selected_station):
                    st.markdown(f"⭐ M{selected_eq['magnitude']:.1f} | Dybde {selected_eq['depth_km']:.1f} km")
                    
                    if stations:
                        st.markdown('<p style="font-size: 14px; margin: 5px 0;">TILGÆNGELIGE STATIONER:</p>', unsafe_allow_html=True)
                        
                        iris_verified = sum(1 for s in stations if s.get('data_source') == 'IRIS_INVENTORY')
                        fallback_count = len(stations) - iris_verified
                        
                        # STATION BUTTONS med clean error handling
                        for i, station in enumerate(stations):
                            station_id = i + 1
                            is_selected = selected_station and station['station'] == selected_station['station']
                            
                            source_indicator = "✅" if station.get('data_source') == 'IRIS_INVENTORY' else "📊"
                            button_color = "🔴" if is_selected else "🔵"
                            button_text = f"{button_color} {station_id}: {station['network']}.{station['station']} ({station['distance_km']:.0f}km) {source_indicator}"
                            
                            if st.button(button_text, key=f"analysis_station_{i}", use_container_width=True):
                                # Ryd tidligere fejlbeskeder
                                if 'station_error_message' in st.session_state:
                                    del st.session_state.station_error_message
                                
                                # Reset analysis state
                                st.session_state.waveform_data = None
                                st.session_state.show_analysis = False
                                st.session_state.selected_station = station
                                
                                # CLEAN download handling
                                with st.spinner(f"📡 Henter data fra {station['network']}.{station['station']}..."):
                                    waveform_data = self.data_manager.download_waveform_data(selected_eq, station)
                                
                                if waveform_data:
                                    # SUCCESS CASE
                                    st.session_state.waveform_data = waveform_data
                                    st.session_state.show_analysis = True
                                    st.session_state.auto_scroll_to_analysis = True  # TILFØJET: Flag for auto-scroll
                                    
                                    # Vis success message kort
                                    components = waveform_data.get('available_components', [])
                                    sample_rate = waveform_data.get('sampling_rate', 'N/A')
                                    st.success(f"✅ Data hentet! Komponenter: {', '.join(components)} @ {sample_rate} Hz")
                                    
                                    # Timing validation feedback
                                    if 'timing_validation' in waveform_data:
                                        validation = waveform_data['timing_validation']
                                        if not validation['is_valid']:
                                            st.warning(f"⚠️ {validation['message']}")
                                            if validation['info']:
                                                info = validation['info']
                                                expected_range = info['realistic_p_range']
                                                st.info(f"💡 Forventet P-ankomst: {expected_range[0]:.1f}-{expected_range[1]:.1f}s")
                                    
                                    # FORBEDRET AUTO-SCROLL - med længere delay
                                    st.markdown("""
                                    <script>
                                    setTimeout(function() {
                                        const analysisElement = document.getElementById('analysis-section');
                                        if (analysisElement) {
                                            analysisElement.scrollIntoView({ 
                                                behavior: 'smooth',
                                                block: 'start'
                                            });
                                        }
                                    }, 2000);
                                    </script>
                                    """, unsafe_allow_html=True)
                                    
                                    st.rerun()

                                    
                                else:
                                    # FAILURE CASE - sæt persistent detailed error
                                    st.session_state.selected_station = None
                                    st.session_state.waveform_data = None
                                    st.session_state.show_analysis = False
                                    
                                    # Sæt persistent error message
                                    st.session_state.station_error_message = {
                                        'message': f"Ingen data tilgængelig for {station['network']}.{station['station']}",
                                        'details': [
                                            f"Station: {station['network']}.{station['station']} ({station['distance_km']:.0f} km fra epicenter)",
                                            f"Jordskælv: M{selected_eq['magnitude']:.1f} den {selected_eq['time'].strftime('%Y-%m-%d %H:%M:%S')} UTC",
                                            f"Søgte tidsperiode: 30 minutter fra jordskælv tidspunkt",
                                            "IRIS returnerede ingen waveform data for denne station/tidspunkt kombination"
                                        ],
                                        'suggestions': [
                                            "Prøv en anden station fra listen ovenfor",
                                            "Stationen var muligvis ikke operationel på jordskælv tidspunktet",
                                            "Der kan være huller i IRIS dataarkivet for denne periode",
                                            "Fallback stationer har ikke garanteret data tilgængelighed" if station.get('data_source') == 'ANALYSIS_READY_FALLBACK' else "IRIS verificerede stationer har generelt bedre data tilgængelighed"
                                        ]
                                    }
                                    # Fjern None værdier hvis nogen
                                    st.session_state.station_error_message['suggestions'] = [
                                        s for s in st.session_state.station_error_message['suggestions'] if s
                                    ]
                                    
                                    # INGEN rerun - lad fejlbeskeden blive synlig
                        
                        # Station kvalitet info
                        if iris_verified > 0:
                            st.success(f"✅ {iris_verified} IRIS verificerede stationer")
                        if fallback_count > 0:
                            st.info(f"ℹ️ {fallback_count} fallback stationer")
                    else:
                        # Hvis ingen stationer fundet
                        st.warning("⚠️ Ingen analyse-klar stationer fundet for dette jordskælv")
                        st.info("💡 Mulige årsager:")
                        st.info("• Jordskælvet er for tæt på eller for langt fra stationer")
                        st.info("• Ingen stationer var operationelle på tidspunktet") 
                        st.info("• Netværksproblemer med IRIS søgning")
                        
                        # Tilbyd at prøve igen
                        if st.button("🔄 Søg stationer igen", key="retry_stations"):
                            st.session_state.pending_station_search = True
                            st.session_state.show_stations = False
                            st.session_state.station_list = []
                            st.rerun()
            else:
                # Når ingen jordskælv er valgt
                if not df.empty:
                    st.metric("Tilgængelige jordskælv", f"{len(df)}")
            
            # ANALYSIS BUTTON - kun vis hvis data er tilgængelig OG der faktisk er noget at analysere
            if st.session_state.get('show_analysis') and st.session_state.get('waveform_data'):
                st.markdown("""
                <style>
                .anonymous-analysis-button {
                    display: block; padding: 0.75rem 1rem; background: #f8f9fa; color: #28a745 !important;
                    text-decoration: none; border-radius: 8px; font-weight: 500; font-size: 16px;
                    border: 1px solid #28a745; cursor: pointer; width: 100%; text-align: center;
                    margin: 1rem 0; transition: all 0.3s ease;
                }
                .anonymous-analysis-button:hover {
                    background: #f1f8e9; color: #218838 !important; border: 2px solid #218838;
                    transform: translateY(-1px);
                }
                </style>
                """, unsafe_allow_html=True)

                st.markdown('<a href="#analysis-section" class="anonymous-analysis-button">KLIK FOR ANALYSE</a>', unsafe_allow_html=True)

    def create_useful_info_window(self):
        """
        Opretter "Nyttig Info" vindue med faglig forklaring og undervisningshjælp.
        Erstatter den gamle brugerguide med mere fokuseret fagligt indhold.
        """
        
        # ANCHOR til Nyttig Info sektion
        st.markdown('<div id="info-section" style="scroll-margin-top: 20px;"></div>', unsafe_allow_html=True)
        
        # Header sektion
        st.subheader("**📚 Nyttig Info & Faglig Hjælp**")
        st.markdown("**Forklaring af faglige metoder, tolkning af data og undervisningsidéer**")
        
        # CSS for styling af info tabs
        st.markdown("""
        <style>
        /* Styling for info tabs */
        .info-content {
            padding: 20px 0;
        }
        
        .info-block {
            background: linear-gradient(135deg, #f8f9fa, #e9ecef) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            margin: 15px 0 !important;
            border-left: 4px solid #007bff !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
        }
        
        .physics-block {
            background: linear-gradient(135deg, #e8f4fd, #f0f8ff) !important;
            border-left-color: #0066cc !important;
        }
        
        .processing-block {
            background: linear-gradient(135deg, #f0fff0, #f5fffa) !important;
            border-left-color: #28a745 !important;
        }
        
        .teaching-block {
            background: linear-gradient(135deg, #fff8dc, #fffacd) !important;
            border-left-color: #ffc107 !important;
        }
        
        .technical-block {
            background: linear-gradient(135deg, #faf0e6, #fdf5e6) !important;
            border-left-color: #fd7e14 !important;
        }
        
        .code-example {
            background: #f8f9fa !important;
            padding: 15px !important;
            border-radius: 8px !important;
            font-family: 'Courier New', monospace !important;
            border: 1px solid #dee2e6 !important;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Hovedtabs for organiseret info
        info_tab1, info_tab2, info_tab3, info_tab4 = st.tabs([
            "🔬 Data & Fysik", "⚙️ Signal Processing", "🎓 Undervisning", "🔧 Teknisk Reference"
        ])
        
        # ==========================================
        # TAB 1: DATA & FYSIK
        # ==========================================
        with info_tab1:
            st.markdown('<div class="info-content">', unsafe_allow_html=True)
            
            # Fra Counts til Displacement
            st.markdown('<div class="info-block physics-block">', unsafe_allow_html=True)
            st.markdown("## 📈 Fra Counts til Displacement")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### Instrument Counts → Ground Velocity
                Seismometre måler elektriske impulser (digitaliserede værdier kaldet *counts*), som svarer til jordens hastighed (velocity). For at få en fysisk enhed (m/s) skal vi korrigere for instrumentets egenskaber:
                """)
                
                st.markdown('<div class="code-example">', unsafe_allow_html=True)
                st.markdown("""
                ```
                Ground velocity (m/s) =  
                (Counts × A/D faktor) / (Gain × Følsomhed)
                ```
                """)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with col2:
                st.markdown("""
                ### Ground Velocity → Displacement
                Ønsker man at se den *faktiske bevægelse af jorden* (displacement), integrerer man signalet over tid:
                """)
                
                st.markdown('<div class="code-example">', unsafe_allow_html=True)
                st.markdown("""
                ```
                Displacement = ∫ Ground_velocity dt
                ```
                """)
                st.markdown('</div>', unsafe_allow_html=True)
            
            st.markdown("""
            ### 📉 Response Removal – hvad sker der?
            *Instrument response* fjernes for at give et realistisk billede af jordens bevægelser:
            - ✅ Kompensation for instrumentets karakteristik
            - ✅ Fjernelse af frekvens-afhængig forstærkning
            - ✅ Konvertering til faktiske fysiske enheder (typisk: m/s eller m)
            - ✅ **Displacement vises i millimeter** i GEOseis (for klarhed og sammenlignelighed)
            
            Et illustrativt skema med denne omregning kan ses i hjælpebilledet, hvor sammenhængen mellem counts og meter fremgår.
            """)
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Seismiske bølgetyper
            st.markdown('<div class="info-block physics-block">', unsafe_allow_html=True)
            st.markdown("## 🌊 Seismiske Bølgetyper")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("""
                ### P-bølger (Primære)
                **Fysik:** Longitudinale kompression/dilatation bølger
                - **Hastighed:** ~8 km/s (først ankommende)
                - **Bevægelse:** Frem-tilbage langs udbredelsesretning
                - **Medium:** Fast stof, væske og gas
                - **Polarisation:** Radial fra epicenter
                - **Synlig på:** Alle tre komponenter
                """)
                
            with col2:
                st.markdown("""
                ### S-bølger (Sekundære)
                **Fysik:** Transversale forskydningsbølger
                - **Hastighed:** ~4.5 km/s (anden ankomst)
                - **Bevægelse:** Side til side vinkelret på udbredelse
                - **Medium:** Kun fast stof (stopper ved flydende kerne)
                - **Polarisation:** Tangential til epicenter
                - **Synlig på:** Især horisontale komponenter
                """)
                
            with col3:
                st.markdown("""
                ### Overfladebølger
                **Fysik:** Komplekse bølger langs jordens overflade
                - **Hastighed:** ~3.5 km/s (sidste ankomst)
                - **Typer:** Rayleigh (elliptisk) og Love (horizontal)
                - **Amplitude:** Ofte største - bruges til Ms
                - **Periode:** 10-50 sekunder
                - **Dæmpning:** Langsom → rejser langt
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Magnitude scales
            st.markdown('<div class="info-block physics-block">', unsafe_allow_html=True)
            st.markdown("## 📊 Ms Magnitude Forklaring")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### IASPEI Standard Formel
                """)
                st.markdown('<div class="code-example">', unsafe_allow_html=True)
                st.markdown("""
                ```
                Ms = log₁₀(A/T) + 1.66×log₁₀(Δ) + 3.3
                ```
                
                **Parameter forklaring:**
                - A: Maksimum amplitude i mikrometers (μm)
                - T: Periode i sekunder (typisk 20s)
                - Δ: Epicentral afstand i grader
                - 1.66: Empirisk geometrisk korrektion
                - 3.3: Empirisk absolutt kalibrering
                """)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with col2:
                st.markdown("""
                ### Klassisk vs. Moderne Ms
                
                **Ms Klassisk (pre-2013):**
                - Bruger største horizontale komponent
                - Enten North eller East - hvilket som helst er størst
                - Historisk standard før IASPEI 2013
                
                **Ms_20 (IASPEI 2013 standard):**
                - Bruger vertikal komponent
                - Mindre påvirket af lokal geologi
                - Mere konsistent mellem stationer
                - **Foretrukken i moderne analyse**
                
                **Optimale betingelser:**
                - Magnitude: M 6.0 - 8.5
                - Afstand: 20° - 160° (2200-17800 km)
                - Dybde: < 50 km (stærke overfladebølger)
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # ==========================================
        # TAB 2: SIGNAL PROCESSING
        # ==========================================
        with info_tab2:
            st.markdown('<div class="info-content">', unsafe_allow_html=True)
            
            # Filtrering
            st.markdown('<div class="info-block processing-block">', unsafe_allow_html=True)
            st.markdown("## 🎛️ Hvorfor bruge filtre?")
            
            st.markdown("""
            Rå seismiske signaler indeholder ofte:
            - **Støj** (elektrisk, atmosfærisk, menneskeskabt)
            - **Uønskede frekvenser** (fx infralyd eller drift)
            - **Lavfrekvente langsomme svingninger**
            
            **Filtre** hjælper med at fjerne støj og fremhæve det relevante signal. I GEOseis bruges typisk **Butterworth-filtre**:
            - Lavpas, højpas eller båndpas
            - Fase-lineære → ingen tidsforvrængning
            - Bruges især ved detektion af P-bølger og overfladebølger
            """)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### Filter Implementering
                """)
                st.markdown('<div class="code-example">', unsafe_allow_html=True)
                st.markdown("""
                ```python
                # Nyquist frekvens check
                nyquist = sampling_rate / 2.0
                max_safe_freq = nyquist * 0.95
                
                # Normaliser til Nyquist
                low_norm = low_freq / nyquist
                high_norm = high_freq / nyquist
                
                # Design Butterworth filter
                b, a = butter(order, [low_norm, high_norm], 
                            btype='band')
                
                # Zero-phase filtering (bevarer timing)
                filtered_data = filtfilt(b, a, data)
                ```
                """)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with col2:
                st.markdown("""
                ### GEOseis Filter Typer
                
                **Original (0.01-25 Hz):**
                - Kun instrument response removal
                - Autentisk men kan være støjfyldt
                
                **Bredband (0.01-25 Hz):**
                - Standard for generel analyse
                - Balancerer støjreduktion og signal bevarelse
                
                **P-bølger (1.0-10.0 Hz):**
                - Høj frekvens - fremhæver skarpe ankomster
                
                **S-bølger (0.5-5.0 Hz):**
                - Medium frekvens til forskydningsbølger
                
                **Overfladebølger (0.02-0.5 Hz):**
                - Lav frekvens - optimal til Ms magnitude
                - Isolerer 10-50 sekund periode bølger
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Signal kvalitet
            st.markdown('<div class="info-block processing-block">', unsafe_allow_html=True)
            st.markdown("## 📈 Signal Kvalitet og SNR")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### Signal-to-Noise Ratio (SNR)
                
                **Definition:**
                ```
                SNR(dB) = 10 × log₁₀(signal_power / noise_power)
                ```
                
                **Kvalitets guidelines:**
                - **SNR > 20 dB:** Fremragende kvalitet
                - **SNR 10-20 dB:** God kvalitet  
                - **SNR < 10 dB:** Begrænset kvalitet
                
                **Beregning i GEOseis:**
                - Støj estimeres fra pre-event data
                - Signal analyseres i overlappende vinduer
                - Kontinuerlig SNR monitoring
                """)
                
            with col2:
                st.markdown("""
                ### Spike Detection og Fjernelse
                
                **Modified Z-Score metode:**
                ```
                Modified Z-Score = 0.6745 × (x - median) / MAD
                ```
                hvor MAD = median(|x - median(x)|)
                
                **Fordele:**
                - Robust mod outliers
                - Bevarer signal kontinuitet
                - Automatisk threshold (typisk 5.0)
                
                **Anvendelse:**
                - Fjerner instrument glitches
                - Bevarer ægte seismiske signaler
                - Erstatter spikes med median-filtrerede værdier
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # ==========================================
        # TAB 3: UNDERVISNING
        # ==========================================
        with info_tab3:
            st.markdown('<div class="info-content">', unsafe_allow_html=True)
            
            # Undervisningseksempler
            st.markdown('<div class="info-block teaching-block">', unsafe_allow_html=True)
            st.markdown("## 🧪 Eksempler og idéer til undervisningsbrug")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### 🧹 1. Beregn Ms-magnitude
                - Hent overfladebølger fra et kendt jordskælv
                - Brug GEOseis til at finde maksimum amplitude og periode
                - Programmet beregner Ms automatisk
                - **Diskutér forskelle mellem målt og rapporteret Ms**
                
                ### 📏 2. Undersøg bølgehastigheder
                - Find ankomsttidspunkter for P- og S-bølger på to eller flere stationer
                - Beregn hastigheder:
                """)
                st.markdown('<div class="code-example">', unsafe_allow_html=True)
                st.markdown("```\nHastighed = Afstand / Tidsforskel\n```")
                st.markdown('</div>', unsafe_allow_html=True)
                st.markdown("- Sammenlign med teoretiske værdier for jordens lag")
                
            with col2:
                st.markdown("""
                ### 🕵️ 3. Find epicenter og test forståelse
                - Brug ankomsttider til at bestemme afstande til epicenteret
                - Anvend fx IRIS' Triangulation Tool:  
                [https://www.iris.edu/app/triangulation](https://www.iris.edu/app/triangulation)
                - Brug tre stationer og sammenlign med USGS-data
                
                ### 📊 4. Filtrering og sammenligning
                - Undersøg signal før og efter filtrering
                - Lad eleverne eksperimentere med filterparametre
                - **Diskutér hvorfor visse signaldele fremhæves og andre forsvinder**
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Faglige koncepter
            st.markdown('<div class="info-block teaching-block">', unsafe_allow_html=True)
            st.markdown("## 📚 Faglige Koncepter til Undervisning")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("""
                ### Fysik Koncepter
                - **Bølgelære:** Longitudinale vs. transversale
                - **Hastighed:** v = f × λ
                - **Amplitude:** Energi og afstand
                - **Frekvens/Periode:** T = 1/f
                - **Interferens:** Konstruktiv/destruktiv
                - **Dæmpning:** Geometrisk spredning
                """)
                
            with col2:
                st.markdown("""
                ### Matematik Koncepter
                - **Logaritmer:** Magnitude skala
                - **Trigonometri:** Bølge polarisation
                - **Statistik:** SNR, støj analyse
                - **Integration:** Velocity til displacement
                - **Eksponentielle funktioner:** Dæmpning
                - **Koordinater:** Afstand på kugleoverflade
                """)
                
            with col3:
                st.markdown("""
                ### Geografi/Naturteknologi
                - **Pladetektonik:** Årsager til jordskælv
                - **Jordens struktur:** Kerne, kappe, skorpe
                - **Naturkatastrofer:** Risiko og forebyggelse
                - **Global overvågning:** Netværk og teknologi
                - **Data analyse:** Fra målinger til erkendelse
                - **Instrumentering:** Sensorer og kalibrering
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Nyttige ressourcer
            st.markdown('<div class="info-block teaching-block">', unsafe_allow_html=True)
            st.markdown("## 🌍 Nyttige Ressourcer")
            
            st.markdown("""
            ### Interaktive Værktøjer
            **IRIS Seismic Wave Simulator:**  
            [https://ds.iris.edu/seismon/swaves/index.php](https://ds.iris.edu/seismon/swaves/index.php)
            - Se hvordan bølger brydes og reflekteres i jordens lag
            - Forklare hvorfor data kan være svære at tolke
            - Understøtte undervisning om P- og S-bølger, overfladebølger, og "shadow zones"
            
            **IRIS Triangulation Tool:**  
            [https://www.iris.edu/app/triangulation](https://www.iris.edu/app/triangulation)
            - Praktisk epicenter bestemmelse
            - Brug reelle stationsdata
            
            **IRIS WILBER3 Interface:**  
            [https://ds.iris.edu/wilber3](https://ds.iris.edu/wilber3)
            - Samme data som GEOseis bruger
            - Detaljeret station information
            - Avancerede søgemuligheder
            """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        
        # ==========================================
        # TAB 4: TEKNISK REFERENCE
        # ==========================================
        with info_tab4:
            st.markdown('<div class="info-content">', unsafe_allow_html=True)
            
            # Data format og standarder
            st.markdown('<div class="info-block technical-block">', unsafe_allow_html=True)
            st.markdown("## 🔧 Data Format og Standarder")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### SEED Format
                **Standard for Exchange of Earthquake Data**
                - Global standard for seismiske data
                - Inkluderer både data og metadata
                - Station koordinater, instrument respons
                - Timing information med μs præcision
                
                ### FDSN Web Services
                **Federation of Digital Seismograph Networks**
                - Standardiseret API til data adgang
                - Dataselect, Station, Event services
                - RESTful interface - nem integration
                - Brugt af GEOseis til IRIS adgang
                """)
                
            with col2:
                st.markdown("""
                ### Instrument Response
                **Poles and Zeros representation:**
                - Beskriver instrument karakteristik
                - Frekvens-afhængig forstærkning og fase
                - Nødvendig for kalibrering til fysiske enheder
                - Automatisk håndteret af ObsPy
                
                ### Timing Præcision
                **GPS baseret timing:**
                - μs præcision i moderne stationer
                - Kritisk for præcise ankomsttider
                - Automatisk korrektion for klok drift
                - GEOseis validerer timing konsistens
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Netværk og station koder
            st.markdown('<div class="info-block technical-block">', unsafe_allow_html=True)
            st.markdown("## 🌐 Netværk og Station Koder")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### Højkvalitets Netværk
                **IU - Global Seismographic Network (GSN):**
                - Højeste kvalitets globale stationer
                - Bredband, høj dynamisk range
                - Real-time data transmission
                - Eksempler: ANMO, COLA, GRFO
                
                **II - Global Seismographic Network:**
                - Supplerende GSN stationer
                - Samme høje standarder
                - Eksempler: BFO, PFO, KRIS
                
                **G - GEOSCOPE (Frankrig):**
                - Fransk globalt bredband netværk
                - Høj kvalitet, pålidelig drift
                - Eksempler: SSB, ECH, UNM
                """)
                
            with col2:
                st.markdown("""
                ### Regionale Netværk
                **GE - GEOFON (Tyskland):**
                - Tysk globalt netværk
                - Fokus på tektonisk aktive områder
                - Eksempler: WLF, STU, IBBN
                
                **CN - Canadian National Network:**
                - Dækker Canada og arktis
                - Vigtig for nordlig hemisphære dækning
                - Eksempler: YKA, SCHQ
                
                **US - United States Network:**
                - Omfattende dækning af USA
                - Komplementerer GSN stationer
                - Eksempler: LRAL, mange andre
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            
            # GEOseis implementation
            st.markdown('<div class="info-block technical-block">', unsafe_allow_html=True)
            st.markdown("## ⚙️ GEOseis Implementation Detaljer")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                ### ObsPy Integration
                **Python bibliotek til seismologi:**
                - Standard i det seismologiske community
                - Håndterer SEED data automatisk
                - Instrument response removal
                - TauP rejsetids beregninger
                
                ### Streamlit Framework
                **Moderne web app framework:**
                - Reaktiv bruger interface
                - Interaktive plots med Plotly
                - Session state management
                - Easy deployment
                """)
                
            with col2:
                st.markdown("""
                ### Data Processing Pipeline
                **1. Data Hentning:**
                - IRIS FDSN client
                - Automatisk station søgning
                - Timing validering
                
                **2. Signal Processing:**
                - Butterworth filtrering
                - Spike detection/removal
                - SNR beregning
                
                **3. Analysis:**
                - Ms magnitude beregning
                - FFT spektral analyse
                - P-wave detection
                
                **4. Export:**
                - Excel format med metadata
                - Downsampling til effektivitet
                - Komplet analyse dokumentation
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    def update_navigation_panel_with_info(self):
        """Navigation panel med KORREKT fixed position - over filtermenuen."""
        
        # Check om vi skal vise navigation panel
        if not (st.session_state.get('show_analysis') and st.session_state.get('waveform_data')):
            return
        
        # NAVIGATION PANEL HTML - FIXED POSITION som ønsket
        nav_html = """
        <style>
        .navigation-panel {
            /* FIXED POSITION - over filtermenuen */
            position: fixed;
            top: 80px;           /* 180px fra toppen som ønsket */
            right: 100px;          /* 20px fra højre side */
            z-index: 1000;
            
            /* Bredde matcher filtermenuen */
            width: 350px;         /* Samme bredde som filtermenu */
            max-width: 90vw;      /* Responsive på små skærme */
            
            /* Styling */
            background: rgba(248, 249, 250, 0.95);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(200, 200, 200, 0.3);
            border-radius: 8px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            
            /* Layout */
            display: flex;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        }

        .nav-button {
            padding: 12px 16px;
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            background: transparent;
            transition: all 0.2s ease;
            cursor: pointer;
            border-right: 1px solid rgba(200, 200, 200, 0.3);
            
            /* Lige fordeling af plads */
            flex: 1;
            text-align: center;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            min-width: 0;
        }

        .nav-button:last-child {
            border-right: none;
        }

        /* HJEM knap */
        .nav-button.home {
            color: #6c757d;
        }
        .nav-button.home:hover {
            background: rgba(108, 117, 125, 0.1);
            color: #495057;
            text-decoration: none;
        }

        /* ANALYSE knap */
        .nav-button.analysis {
            color: #28a745;
        }
        .nav-button.analysis:hover {
            background: rgba(40, 167, 69, 0.1);
            color: #218838;
            text-decoration: none;
        }

        /* NYTTIG INFO knap */
        .nav-button.info {
            color: #fd7e14;
        }
        .nav-button.info:hover {
            background: rgba(253, 126, 20, 0.1);
            color: #e8590c;
            text-decoration: none;
        }

        /* GRØN FIRKANT MED LYN IKON */
        .analysis-icon-square {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 4px;
            background: #c9e0c1;
            color: white;
            font-size: 12px;
            font-weight: normal;
            font-family: Arial, sans-serif;
        }

        /* Hover effekt for grøn firkant */
        .nav-button.analysis:hover .analysis-icon-square {
            background: #218838;
            transform: scale(1.1);
            transition: all 0.2s ease;
        }

        /* ORANGE CIRKEL MED "i" IKON */
        .info-icon-circle {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: #fd7e14;
            color: white;
            font-size: 12px;
            font-weight: bold;
            font-family: Arial, sans-serif;
            font-style: italic;
        }

        /* Hover effekt for orange cirkel */
        .nav-button.info:hover .info-icon-circle {
            background: #e8590c;
            transform: scale(1.1);
            transition: all 0.2s ease;
        }

        .nav-button:visited {
            text-decoration: none;
        }

        /* Responsive tilpasning */
        @media (max-width: 768px) {
            .navigation-panel {
                position: relative;    /* Skift til relative på små skærme */
                top: auto;
                right: auto;
                margin: 10px auto;
                width: 100%;
                max-width: 400px;
            }
            
            .nav-button {
                font-size: 13px;
                padding: 10px 12px;
                gap: 4px;
            }
            
            .analysis-icon-square,
            .info-icon-circle {
                width: 16px;
                height: 16px;
                font-size: 11px;
            }
        }

        @media (max-width: 480px) {
            .nav-button span:last-child {
                display: none;  /* Skjul tekst på meget små skærme */
            }
            .nav-button {
                padding: 8px 10px;
            }
        }
        </style>

        <div class="navigation-panel">
            <a href="#map-section" class="nav-button home">
                <span>⌂</span>
                <span>HJEM</span>
            </a>
            <a href="#analysis-section" class="nav-button analysis">
                <span class="analysis-icon-square">⚡</span>
                <span>ANALYSE</span>
            </a>
            <a href="#info-section" class="nav-button info">
                <span class="info-icon-circle">i</span>
                <span>INFO</span>
            </a>
        </div>
        """
        
        # Render navigation panel
        st.markdown(nav_html, unsafe_allow_html=True)

    # HVIS BREDDEN IKKE MATCHER PRÆCIST, kan du justere disse værdier:
    # 
    # top: 180px        <- Juster denne for vertikal position
    # right: 100px       <- Juster denne for horisontal position  
    # width: 350px      <- Juster denne for at matche filtermenuen's bredde
    #
    # For at finde den eksakte bredde af filtermenuen, kan du:
    # 1. Højreklik på filtermenuen i browseren
    # 2. Vælg "Inspect Element" 
    # 3. Se bredden i CSS panelet
    # 4. Opdater width: værdi tilsvarende


#=======================       
#  Analysedel start      
#========================    
    def create_enhanced_analysis_window_updated(self):
        """
        Opdateret version af analyse vindue der:
        1. FJERNER den gamle brugerguide (tab 4)
        2. Opdaterer navigation til at inkludere "Nyttig Info"
        3. Kalder den nye useful info når relevant
        
        Skal erstatte den nuværende create_enhanced_analysis_window metode.
        """
        selected_eq = st.session_state.get('selected_earthquake')
        selected_station = st.session_state.get('selected_station')
        waveform_data = st.session_state.get('waveform_data')
        
        # Kræv alle kritiske komponenter før visning
        if not all([selected_eq, selected_station, waveform_data]):
            return
        
        # ANCHOR TIL ANALYSE SEKTION
        st.markdown('<div id="analysis-section" style="scroll-margin-top: 20px;"></div>', unsafe_allow_html=True)

        # AUTO-SCROLL HANDLING - samme som før
        if st.session_state.get('auto_scroll_to_analysis', False):
            st.session_state.auto_scroll_to_analysis = False
            st.markdown("""
            <script>
            let attempts = 0;
            const maxAttempts = 10;
            
            function scrollToAnalysis() {
                const element = document.getElementById('analysis-section');
                if (element && attempts < maxAttempts) {
                    element.scrollIntoView({ 
                        behavior: 'smooth',
                        block: 'start',
                        inline: 'nearest'
                    });
                } else if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(scrollToAnalysis, 200);
                }
            }
            
            setTimeout(scrollToAnalysis, 1000);
            </script>
            """, unsafe_allow_html=True)

        # Header sektion
        st.subheader(f"**📈 Analyse: {selected_station['network']}.{selected_station['station']}**")
        
        # Timing validation samme som før
        if 'timing_validation' in waveform_data:
            validation = waveform_data['timing_validation']
            if not validation['is_valid']:
                st.warning(f"⚠️ {validation['message']}")
                if validation['info']:
                    info = validation['info']
                    expected_range = info['realistic_p_range']
                    st.info(f"💡 Forventet: {expected_range[0]:.1f}-{expected_range[1]:.1f}s (observeret: {info['p_arrival_time']:.1f}s)")
        
        # CSS for styling - samme som før men tilføjet info knap styling
        st.markdown("""
        <style>
        /* Eksisterende tab styling... */
        .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
            padding: 8px 16px !important;
        }
        
        /* Navigation panel opdatering */
        .nav-button.info {
            color: #6f42c1;
            min-width: 85px;
        }
        .nav-button.info:hover {
            background: rgba(111, 66, 193, 0.1);
            color: #5a2d91;
            text-decoration: none;
        }
        
        /* Alle andre eksisterende styles... */
        </style>
        """, unsafe_allow_html=True)
        
        # OPDATERET NAVIGATION PANEL - nu med Nyttig Info
        self.update_navigation_panel_with_info()
        
        # OPDATEREDE TABS - KUN 3 tabs nu, brugerguide er fjernet
        tab1, tab2, tab3 = st.tabs(["📊 Basis Analyse", "🔬 Avanceret", "📤 Export & Info"])
        
        # TAB 1 og TAB 2 samme som før...
        # [Hele tab1 og tab2 indhold kopieres fra original - for korthed udeladt her]
        
        # TAB 3: Export & Info (samme som før)
        with tab3:
            # [Eksisterende tab3 indhold kopieres fra original]
            pass

# Tilføj denne metode til run() metoden for at håndtere info vindue

    def create_enhanced_analysis_window(self):
        """
        Opretter avanceret analyse vindue med tab-baseret interface for bedre overskuelighed.
        VERSION: 2.4 - Forbedret navigation panel og auto-scroll
        """
        selected_eq = st.session_state.get('selected_earthquake')
        selected_station = st.session_state.get('selected_station')
        waveform_data = st.session_state.get('waveform_data')
        
        # Kræv alle kritiske komponenter før visning
        if not all([selected_eq, selected_station, waveform_data]):
            return
        
        # TILFØJ ANCHOR TIL ANALYSE SEKTION
        st.markdown('<div id="analysis-section" style="scroll-margin-top: 20px;"></div>', unsafe_allow_html=True)

        # AUTO-SCROLL HANDLING - Forbedret version
        if st.session_state.get('auto_scroll_to_analysis', False):
            st.session_state.auto_scroll_to_analysis = False  # Reset flag
            st.markdown("""
            <script>
            // Forsøg flere gange hvis element ikke er klar
            let attempts = 0;
            const maxAttempts = 10;
            
            function scrollToAnalysis() {
                const element = document.getElementById('analysis-section');
                if (element && attempts < maxAttempts) {
                    element.scrollIntoView({ 
                        behavior: 'smooth',
                        block: 'start',
                        inline: 'nearest'
                    });
                } else if (attempts < maxAttempts) {
                    attempts++;
                    setTimeout(scrollToAnalysis, 200);
                }
            }
            
            setTimeout(scrollToAnalysis, 1000);
            </script>
            """, unsafe_allow_html=True)

        # Header sektion
        st.subheader(f"**📈 Analyse: {selected_station['network']}.{selected_station['station']}**")
        
        # Vis kun timing problemer hvis de eksisterer
        if 'timing_validation' in waveform_data:
            validation = waveform_data['timing_validation']
            if not validation['is_valid']:
                st.warning(f"⚠️ {validation['message']}")
                if validation['info']:
                    info = validation['info']
                    expected_range = info['realistic_p_range']
                    st.info(f"💡 Forventet: {expected_range[0]:.1f}-{expected_range[1]:.1f}s (observeret: {info['p_arrival_time']:.1f}s)")
        
       # CSS for styling af tab indhold - KUN basis styling
        st.markdown('''
        <style>
        /* Tab styling */
        .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
            font-size: 16px !important;
            padding: 8px 16px !important;
        }
        
        .stTabs [data-baseweb="tab-list"] {
            gap: 20px !important;
        }
        
        .stTabs [data-baseweb="tab-list"] button {
            height: auto !important;
            padding: 12px 20px !important;
            border-radius: 12px !important;
        }
        
        .tab-content {
            padding: 10px 0;
        }
        .metric-container {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
            border-left: 4px solid #007bff;
        }
        .analysis-section {
            margin: 20px 0;
        }
        
        /* Info window styling */
        .guide-understand {
            background: linear-gradient(135deg, #e8f4fd, #f0f8ff) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            margin: 15px 0 !important;
        }
        
        .guide-filters {
            background: linear-gradient(135deg, #f0fff0, #f5fffa) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            margin: 15px 0 !important;
        }
        
        .guide-magnitude {
            background: linear-gradient(135deg, #fff8dc, #fffacd) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            margin: 15px 0 !important;
        }
        
        .guide-about {
            background: linear-gradient(135deg, #faf0e6, #fdf5e6) !important;
            padding: 25px !important;
            border-radius: 12px !important;
            margin: 15px 0 !important;
        }
        
        .content-block {
            background: rgba(255, 255, 255, 0.8) !important;
            padding: 20px !important;
            border-radius: 10px !important;
            margin: 15px 5px !important;
            border-left: 4px solid #007bff !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
        }
        
        /* Checkbox styling */
        .stCheckbox {
            margin-bottom: 2px !important;
        }
        
        .stCheckbox > label {
            margin-bottom: 0px !important;
        }
        </style>
        ''', unsafe_allow_html=True)
        
        # NAVIGATION PANEL - Nu med korrekt placering
        self.update_navigation_panel_with_info()
        
        # HOVEDTABS - Organiseret workflow  
        tab1, tab2, tab3 = st.tabs(["📊 Basis Analyse", "🔬 Avanceret", "📤 Export & Info"])

        # ==========================================
        # TAB 1: BASIS ANALYSE - VERSION 2.2 KOMPAKT
        # ==========================================
        with tab1:
            st.markdown('<div class="tab-content">', unsafe_allow_html=True)
            
            # ENKELT kombineret kontrolpanel
            with st.expander("Vælg filter og komponenter", expanded=True):
                col1, col2, col3, col4, col5,col6  = st.columns([2, 1, 1, 1,1,1])
                
                with col1:
                    filter_options = {
                        'raw': 'Original data (ingen filtrering)',
                        'broadband': 'Bredband filter (standard)',
                        'surface': 'Overfladebølger (til Ms magnitude) ⭐',
                        'p_waves': 'P-bølger',
                        's_waves': 'S-bølger'
                    }
                    
                    selected_filter = st.selectbox(
                        "Filtertype:",
                        options=list(filter_options.keys()),
                        format_func=lambda x: filter_options[x],
                        index=1,
                        key="filter_selection_tab1"
                    )
                    
                with col2:
                    remove_spikes = st.checkbox("Fjern spikes", value=True, key="remove_spikes_tab1")
                    
                with col3:
                    show_noise_stats = st.checkbox("Støj-analyse", value=True, key="show_noise_tab1")
                with col4:
                    
                    show_north = st.checkbox("Vis Nord (N)", value=True, key="show_north_tab1")
                    
                with col5:
                    show_east = st.checkbox("Vis Øst (E)", value=True, key="show_east_tab1")
                    
                with col6:
                    show_vertical = st.checkbox("Vis Vertikal (Z)", value=True, key="show_vertical_tab1")    
            
            # Processer data
            try:
                enhanced_processor = self.data_manager.processor
                
                # Forbered data med arrival times
                waveform_data_with_arrivals = waveform_data.copy()
                waveform_data_with_arrivals['arrival_times'] = {
                    'P': selected_station.get('p_arrival'),
                    'S': selected_station.get('s_arrival'), 
                    'Surface': selected_station.get('surface_arrival')
                }
                
                # Processer data
                processed_data = enhanced_processor.process_waveform_with_filtering(
                    waveform_data_with_arrivals,
                    filter_type=selected_filter,
                    remove_spikes=remove_spikes,
                    calculate_noise=show_noise_stats
                )
                
                if processed_data:
                    times = waveform_data['time']
                    sampling_rate = waveform_data['sampling_rate']
                    filtered_data = processed_data['filtered_data']
                    
                    # Beregn Ms magnitude
                    ms_magnitude, ms_explanation = enhanced_processor.calculate_ms_magnitude(
                        filtered_data['north'], filtered_data['east'], filtered_data['vertical'],
                        selected_station['distance_km'], sampling_rate
                    )
                    
                    # Brugervejledning OVER grafen - foldet ind som standard
                    with st.expander("💡 Sådan læser du grafen", expanded=False):
                        st.info("""
                        - **Lodrette linjer** viser teoretiske ankomsttider for P-, S- og overfladebølger
                        - **Amplitude** (y-akse) er jordens bevægelse i millimeter
                        - **Tid** (x-akse) er sekunder efter jordskælvet
                        - **Klik på legend** for at skjule/vise komponenter
                        """)
                    
                    # HOVEDGRAF - Forenklet seismogram
                    fig = go.Figure()
                    
                    # Tilføj komponenter baseret på brugervalg
                    if show_north:
                        fig.add_trace(go.Scatter(x=times, y=filtered_data['north'], 
                                            mode='lines', name='North', 
                                            line=dict(color='red', width=1)))
                    if show_east:
                        fig.add_trace(go.Scatter(x=times, y=filtered_data['east'], 
                                            mode='lines', name='East', 
                                            line=dict(color='green', width=1)))
                    if show_vertical:
                        fig.add_trace(go.Scatter(x=times, y=filtered_data['vertical'], 
                                            mode='lines', name='Vertical', 
                                            line=dict(color='blue', width=1)))
                    
                    # Tilføj arrival times
                    arrivals = [
                        (selected_station.get('p_arrival'), 'P-bølge', 'red'),
                        (selected_station.get('s_arrival'), 'S-bølge', 'blue'),
                        (selected_station.get('surface_arrival'), 'Overfladebølge', 'green')
                    ]
                    
                    for arrival_time, phase, color in arrivals:
                        if arrival_time is not None:
                            fig.add_vline(x=arrival_time, line=dict(color=color, width=2, dash='dash'),
                                        annotation_text=phase)
                    
                    # Graf styling
                    filter_name = filter_options[selected_filter].replace('🔹 ', '').split(' (')[0]
                    fig.update_layout(
                        title=f"Seismogram: {selected_station['network']}.{selected_station['station']} - {filter_name}",
                        xaxis_title="Tid efter jordskælv (sekunder)",
                        yaxis_title="Forskydning (mm)",
                        height=500,
                        showlegend=True
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # VIGTIGE RESULTATER - Metrics display
                    st.markdown("### Resultater af analyse")
                    
                    col1, col2, col3, col4, col5 = st.columns(5)
                    
                    with col1:
                        st.metric("Afstand", f"{selected_station['distance_km']:.0f} km")
                        
                    with col2:
                        p_arrival = selected_station.get('p_arrival')
                        st.metric("P-ankomst", f"{p_arrival:.1f} s" if p_arrival else "N/A")
                        
                    with col3:
                        s_arrival = selected_station.get('s_arrival')
                        st.metric("S-ankomst", f"{s_arrival:.1f} s" if s_arrival else "N/A")
                        
                    with col4:
                        if ms_magnitude:
                            st.metric("Ms Magnitude", f"{ms_magnitude}")
                        else:
                            st.metric("Ms Magnitude", "N/A")
                            
                    with col5:
                        # Beregn maksimum amplitude
                        max_amp = max(
                            np.max(np.abs(filtered_data['north'])) if show_north else 0,
                            np.max(np.abs(filtered_data['east'])) if show_east else 0,
                            np.max(np.abs(filtered_data['vertical'])) if show_vertical else 0
                        )
                        st.metric("Max amplitude", f"{max_amp:.2f} mm")
                    
                    # Ms magnitude forklaring
                    if ms_magnitude and ms_explanation:
                        with st.expander("Ms Magnitude Detaljer"):
                            st.markdown(ms_explanation)
                            
            except Exception as e:
                st.error(f"❌ Analyse fejl: {str(e)}")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # ==========================================
        # TAB 2: AVANCERET ANALYSE
        # ==========================================
        with tab2:
            st.markdown('<div class="tab-content">', unsafe_allow_html=True)
            
            # Avancerede visualiseringer
            st.markdown("### Avancerede Analyser")
            
            col1, col2 = st.columns(2)
            
            with col1:
                show_fft_plot = st.checkbox("FFT spektrum analyse", value=True, key="fft_tab2")  # Nu default aktiveret
                show_snr_plot = st.checkbox("Signal-to-Noise Ratio", value=False, key="snr_tab2")
                show_raw_data = st.checkbox("Rådata (counts)", value=False, key="raw_tab2")
                
            with col2:
                show_p_analysis = st.checkbox("P-bølge detaljeret zoom", value=False, key="p_analysis_tab2")
                show_all_filters = st.checkbox("Sammenlign alle filtre", value=False, key="all_filters_tab2")
            
            # Brug samme processed_data fra Tab 1
            if 'processed_data' in locals() and processed_data:
                
                # Sammenlign alle filtre
                if show_all_filters:
                    st.markdown("#### Sammenligning af Alle Filtre")
                    
                    # Proces data med forskellige filtre
                    filter_types = ['raw', 'broadband', 'p_waves', 's_waves', 'surface']
                    filter_names = {
                        'raw': 'Original',
                        'broadband': 'Bredband', 
                        'p_waves': 'P-bølger',
                        's_waves': 'S-bølger',
                        'surface': 'Overfladebølger'
                    }
                    
                    all_filters_fig = go.Figure()
                    colors = ['gray', 'blue', 'red', 'green', 'orange']
                    
                    component = 'vertical'  # Brug vertikal komponent til sammenligning
                    
                    for i, filter_type in enumerate(filter_types):
                        try:
                            # Proces med hver filter type
                            filter_processed = enhanced_processor.process_waveform_with_filtering(
                                waveform_data_with_arrivals,
                                filter_type=filter_type,
                                remove_spikes=False,  # Undgå spike removal for sammenligning
                                calculate_noise=False
                            )
                            
                            if filter_processed:
                                filtered_signal = filter_processed['filtered_data'][component]
                                
                                all_filters_fig.add_trace(go.Scatter(
                                    x=times, y=filtered_signal,
                                    mode='lines', 
                                    name=filter_names[filter_type],
                                    line=dict(color=colors[i], width=2 if filter_type == 'surface' else 1),
                                    opacity=0.8
                                ))
                        except Exception as e:
                            continue  # Spring over hvis filter fejler
                    
                    # Tilføj arrival times
                    for arrival_time, phase, color in arrivals:
                        if arrival_time is not None:
                            all_filters_fig.add_vline(
                                x=arrival_time, 
                                line=dict(color=color, width=2, dash='dash'),
                                annotation_text=phase
                            )
                    
                    all_filters_fig.update_layout(
                        title="Sammenligning af Alle Filter Typer (Vertikal komponent)",
                        xaxis_title="Tid (s)",
                        yaxis_title="Forskydning (mm)",
                        height=500,
                        showlegend=True
                    )
                    
                    st.plotly_chart(all_filters_fig, use_container_width=True)
                    
                    st.info("""
                    **Filter sammenligning:**
                    - **Original (grå):** Kun response removal
                    - **Bredband (blå):** Standard filter til generel analyse
                    - **P-bølger (rød):** Fremhæver høj-frekvens signaler
                    - **S-bølger (grøn):** Medium frekvens forskydningsbølger
                    - **Overfladebølger (orange, tyk):** Lav-frekvens, optimal til Ms
                    """)
                
                # FFT spektrum analyse
                if show_fft_plot:
                    st.markdown("#### Frekvensanalyse (FFT)")
                    
                    surface_arrival = selected_station.get('surface_arrival')
                    if surface_arrival:
                        # FFT på dominerende horizontale komponent
                        max_north = np.max(np.abs(filtered_data['north']))
                        max_east = np.max(np.abs(filtered_data['east']))
                        dominant_horizontal = filtered_data['north'] if max_north > max_east else filtered_data['east']
                        
                        periods, fft_amplitudes, peak_period, peak_amplitude = enhanced_processor.calculate_surface_wave_fft(
                            dominant_horizontal, sampling_rate, surface_arrival
                        )
                        
                        if periods is not None:
                            fft_fig = go.Figure()
                            fft_fig.add_trace(go.Scatter(
                                x=periods, y=fft_amplitudes,
                                mode='lines', name='FFT Spektrum',
                                line=dict(color='purple', width=2)
                            ))
                            
                            if peak_period and peak_amplitude:
                                fft_fig.add_trace(go.Scatter(
                                    x=[peak_period], y=[peak_amplitude],
                                    mode='markers', name=f'Peak: {peak_period:.1f}s',
                                    marker=dict(color='red', size=12, symbol='star')
                                ))
                            
                            fft_fig.update_layout(
                                title="FFT Spektrum - Overfladebølger",
                                xaxis_title="Periode (sekunder)",
                                yaxis_title="FFT Amplitude",
                                xaxis_type="log",
                                height=400
                            )
                            
                            st.plotly_chart(fft_fig, use_container_width=True)
                            
                            if peak_period:
                                if abs(peak_period - 20.0) < 5.0:
                                    st.success(f"✅ Peak periode ({peak_period:.1f}s) er optimal for Ms beregning (~20s)")
                                else:
                                    st.warning(f"⚠️ Peak periode ({peak_period:.1f}s) afviger fra optimal 20s")
                
                # P-bølge detaljeret analyse
                if show_p_analysis:
                    st.markdown("####  P-bølge - Detaljeret Analyse")
                    
                    p_fig, peak_info = enhanced_processor.create_p_wave_zoom_plot(
                        waveform_data, selected_station, processed_data
                    )
                    
                    if p_fig and peak_info:
                        st.plotly_chart(p_fig, use_container_width=True)
                        
                        # Detektion resultater
                        col1, col2, col3 = st.columns(3)
                        for i, peak in enumerate(peak_info):
                            with [col1, col2, col3][i % 3]:
                                st.metric(
                                    f"{peak['component'].capitalize()}",
                                    f"{peak['time']:.1f}s",
                                    delta=f"{peak['delay']:+.1f}s"
                                )
                                st.caption(f"STA/LTA: {peak['sta_lta']:.1f}")
                
                # SNR plot
                if show_snr_plot and 'snr_data' in processed_data:
                    st.markdown("#### Signal-to-Noise Ratio")
                    
                    snr_fig = go.Figure()
                    
                    for component, snr_info in processed_data['snr_data'].items():
                        snr_fig.add_trace(go.Scatter(
                            x=snr_info['times'], y=snr_info['snr_db'],
                            mode='lines', name=f'SNR {component.capitalize()}',
                            line=dict(width=2)
                        ))
                    
                    # Tilføj SNR kvalitets guidelines
                    snr_fig.add_hline(y=20, line_dash="dash", line_color="green", 
                                    annotation_text="Fremragende kvalitet (>20 dB)")
                    snr_fig.add_hline(y=10, line_dash="dash", line_color="orange", 
                                    annotation_text="God kvalitet (>10 dB)")
                    
                    snr_fig.update_layout(
                        title="Signal-to-Noise Ratio over tid",
                        xaxis_title="Tid (s)",
                        yaxis_title="SNR (dB)",
                        height=400
                    )
                    
                    st.plotly_chart(snr_fig, use_container_width=True)
                
                # Rådata visning
                if show_raw_data:
                    st.markdown("####  Rådata (Instrument Counts)")
                    
                    raw_fig = go.Figure()
                    raw_data = waveform_data['raw_data']
                    
                    raw_fig.add_trace(go.Scatter(x=times, y=raw_data['north'], 
                                            mode='lines', name='North (raw)', 
                                            line=dict(color='red', width=1)))
                    raw_fig.add_trace(go.Scatter(x=times, y=raw_data['east'], 
                                            mode='lines', name='East (raw)', 
                                            line=dict(color='green', width=1)))
                    raw_fig.add_trace(go.Scatter(x=times, y=raw_data['vertical'], 
                                            mode='lines', name='Vertical (raw)', 
                                            line=dict(color='blue', width=1)))
                    
                    raw_fig.update_layout(
                        title="Rådata fra seismometer (instrument counts)",
                        xaxis_title="Tid (s)",
                        yaxis_title="Counts",
                        height=400
                    )
                    
                    st.plotly_chart(raw_fig, use_container_width=True)
                    
                    st.info("ℹ️ Rådata viser direkte output fra seismometer før kalibrering til fysiske enheder")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        # ==========================================
        # TAB 3: EXPORT & INFO
        # ==========================================
        with tab3:
            st.markdown('<div class="tab-content">', unsafe_allow_html=True)
            
            # Excel Export sektion
            st.markdown("### Data Export")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown("""
                **Hvad inkluderes i Excel filen:**
                - 📊 Komplet metadata (jordskælv, station, afstande)
                - 📈 Tidsserier data (både rådata og displacement)
                - 📏 Ms magnitude beregning og resultater
                - ⏱️ Timing information og validering
                - 🔧 Processing parametre og kvalitetsmål
                """)
                
            with col2:
                # Export knap med current settings
                export_filter = st.selectbox(
                    "Export med filter:",
                    options=['raw', 'broadband', 'surface'],
                    format_func=lambda x: {'raw': 'Original data', 'broadband': 'Bredband', 'surface': 'Overfladebølger'}[x],
                    index=1
                )
                
                if st.button("📊 Generer Excel Fil", type="primary", use_container_width=True):
                    try:
                        # Generer processeret data til export
                        export_processed = enhanced_processor.process_waveform_with_filtering(
                            waveform_data_with_arrivals, 
                            filter_type=export_filter,
                            remove_spikes=True
                        )
                        
                        if export_processed:
                            # Beregn Ms med export data
                            export_ms, export_explanation = enhanced_processor.calculate_ms_magnitude(
                                export_processed['filtered_data']['north'], 
                                export_processed['filtered_data']['east'], 
                                export_processed['filtered_data']['vertical'],
                                selected_station['distance_km'], 
                                sampling_rate
                            )
                            
                            # Forbered export data
                            export_waveform = waveform_data.copy()
                            export_waveform['displacement_data'] = export_processed['filtered_data']
                            
                            with st.spinner("📊 Genererer Excel fil..."):
                                excel_data = self.data_manager.export_to_excel(
                                    selected_eq, selected_station, export_waveform, 
                                    export_ms, export_explanation
                                )
                                
                                if excel_data:
                                    filter_suffix = "" if export_filter == 'raw' else f"_{export_filter}"
                                    filename = f"seismic_analysis_{selected_station['network']}_{selected_station['station']}_{selected_eq['time'].strftime('%Y%m%d')}{filter_suffix}.xlsx"
                                    
                                    st.download_button(
                                        label="⬇️ Download Excel Fil",
                                        data=excel_data,
                                        file_name=filename,
                                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                    )
                                    
                                    st.success(f"✅ Excel fil klar til download!")
                                else:
                                    st.error("❌ Kunne ikke generere Excel fil")
                    
                    except Exception as e:
                        st.error(f"❌ Export fejl: {str(e)}")
            
            st.markdown("---")
            
            # Data kvalitet og information
            st.markdown("### ℹ️ Data Information")
            
            # Station og jordskælv info
            info_col1, info_col2 = st.columns(2)
            
            with info_col1:
                st.markdown("**🌍 Jordskælv Information:**")
                st.info(f"""
                **Magnitude:** {selected_eq['magnitude']:.1f}
                **Koordinater:** {selected_eq['latitude']:.2f}°N, {selected_eq['longitude']:.2f}°E  
                **Dybde:** {selected_eq['depth_km']:.1f} km
                **Tidspunkt:** {selected_eq['time'].strftime('%Y-%m-%d %H:%M:%S')} UTC
                """)
                
            with info_col2:
                st.markdown("**📡 Station Information:**")
                st.info(f"""
                **Station:** {selected_station['network']}.{selected_station['station']}
                **Afstand:** {selected_station['distance_km']:.0f} km ({selected_station['distance_deg']:.1f}°)
                **Komponenter:** {', '.join(waveform_data.get('available_components', []))}
                **Sampling rate:** {waveform_data.get('sampling_rate', 'N/A')} Hz
                """)
            
            # Ankomsttider tabel
            st.markdown("**⏱️ Teoretiske Ankomsttider:**")
            arrivals_df = pd.DataFrame({
                'Bølgetype': ['P-bølge', 'S-bølge', 'Overfladebølge'],
                'Ankomsttid (s)': [
                    f"{selected_station.get('p_arrival', 0):.1f}",
                    f"{selected_station.get('s_arrival', 0):.1f}", 
                    f"{selected_station.get('surface_arrival', 0):.1f}"
                ],
                'Hastighed (km/s)': ['~8.0', '~4.5', '~3.5']
            })
            st.dataframe(arrivals_df, use_container_width=True)
            
            # Brugerguide
            with st.expander("📚 Om Graferne"):
                st.markdown("""
                ### Forstå graferne
                **Komponenter:**
                - **North (N):** Bevægelse i nord-syd retning
                - **East (E):** Bevægelse i øst-vest retning  
                - **Vertical (Z):** Op-ned bevægelse
                
                **Bølgetyper:**
                - **P-bølger:** Først ankommende, kompression/udvidelse
                - **S-bølger:** Anden ankomst, forskydning
                - **Overfladebølger:** Kraftigste, brugt til Ms magnitude
                
                ###Filter Typer
                - **Original:** Kun omdannelse til forskydning  (anbefales til begyndere)
                - **Bredband:** Standard filter der fjerner mest støj
                - **Overfladebølger:** Optimal til Ms magnitude beregning
                - **P/S-bølger:** Isolerer specifikke bølgetyper
                
                ###Ms Magnitude
                Ms beregnes fra overfladebølger og er mest pålidelig for jordskælv M > 6.0
                på afstande 20-160 grader. Formlen bruger maksimum amplitude og afstand.
                """)
            
            st.markdown('</div>', unsafe_allow_html=True)
        
       
#=======================
# Analaysedel slut
#=======================    
    def run(self):
            """
            Kører hovedapplikation med komplet workflow.
            
            Koordinerer hele applikations flow:
            1. Vis hovedinterface med kort og kontroller
            2. Håndter bruger interaktioner
            3. Vis analyse vindue når data er klar
            
            Dette er entry point for hele applikationen.
            """
            if st.session_state.data_loaded:
                self.create_main_interface()
                
                # Vis analyse vindue hvis data er klar
                if st.session_state.get('show_analysis', False):
                    self.create_enhanced_analysis_window()
                    st.markdown("---")  # Separator
                    self.create_useful_info_window()


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":
    
    try:
        if OBSPY_AVAILABLE:
            # Initialisér og kør hovedapplikation
            app = StreamlinedSeismicApp()
            app.run()
        else:
            st.error("❌ Denne applikation kræver ObsPy")
            st.info("Installer med: pip install obspy")
            st.info("For conda: conda install -c conda-forge obspy")
            
    except Exception as e:
        # Kritisk fejlhåndtering med brugervenlig feedback
        st.error(f"❌ Kritisk fejl: {e}")
        st.error("Kontakt support eller genstart applikationen")
        
        # Debug information til udviklere
        import traceback
        with st.expander("🔧 Debug Information"):
            st.code(traceback.format_exc())
            
        # Recovery suggestions
        st.info("💡 Prøv at:")
        st.info("- Genindlæse siden...")
        st.info("- Kontrollere ObsPy installation")
        st.info("- Rapportere fejlen hvis problemet fortsætter")
