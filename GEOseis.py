# GEOseis.py v. 3.2.
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
Version: 3.2
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
import plotly.express as px
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import json
import time
import traceback
from scipy import signal
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
    
    def get_valid_filter_bands(self, sampling_rate):
        """
        Beregner gyldige filterbånd baseret på data sampling rate.
        
        Nyquist theorem: Maksimum detektabel frekvens = sampling_rate / 2
        For stabilitet bruges kun 80% af Nyquist frekvensen.
        
        Args:
            sampling_rate (float): Data sampling frekvens i Hz
            
        Returns:
            dict: Dictionary med gyldige filterbånd, justeret efter sampling rate
            
        Example:
            valid_bands = processor.get_valid_filter_bands(100.0)
            # Med 100 Hz sampling: max frekvens = 40 Hz (80% af 50 Hz Nyquist)
        """
        nyquist = sampling_rate / 2.0
        max_freq = nyquist * 0.8  # Brug 80% af Nyquist for stabilitet
        
        valid_bands = {'raw': None}  # Raw data er altid gyldig
        
        # Evaluer hvert filterbånd mod sampling rate begrænsninger
        for filter_name, band in self.filter_bands.items():
            if filter_name == 'raw':
                continue
                
            if band is None:
                continue
                
            low_freq, high_freq = band
            
            # Juster frekvenser hvis de overstiger maksimum
            if high_freq > max_freq:
                if low_freq < max_freq:
                    # Juster øvre frekvens til maksimum mulig
                    adjusted_band = (low_freq, max_freq)
                    valid_bands[f"{filter_name}_adj"] = adjusted_band
                # Hvis nedre frekvens også er for høj, skip dette filter
            else:
                # Filter er fuldt gyldigt
                valid_bands[filter_name] = band
        
        return valid_bands
    
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
    
    def apply_highpass_filter(self, data, sampling_rate, corner_freq, order=None):
        """
        Anvender højpas filter til fjernelse af lave frekvenser (instrument drift).
        
        Højpas filtre er kritiske for at fjerne:
        - Instrument drift og offset
        - Meget lave frekvenser under seismisk interesse
        - DC komponenter
        
        Args:
            data (array): Input seismogram
            sampling_rate (float): Sampling frekvens i Hz
            corner_freq (float): Corner frekvens i Hz
            order (int, optional): Filter orden
            
        Returns:
            array: Højpas filtreret data
        """
        try:
            if order is None:
                order = self.filter_order
                
            nyquist = sampling_rate / 2.0
            corner_norm = corner_freq / nyquist
            
            if corner_norm <= 0 or corner_norm >= 1:
                return data
                
            b, a = butter(order, corner_norm, btype='high')
            return filtfilt(b, a, data)
            
        except Exception as e:
            print(f"Højpas filter fejl: {e}")
            return data
    
    def apply_lowpass_filter(self, data, sampling_rate, corner_freq, order=None):
        """
        Anvender lavpas filter til fjernelse af høje frekvenser (instrument støj).
        
        Lavpas filtre fjerner:
        - Høj-frekvens instrument støj
        - Aliasing artifakter
        - Elektronisk interferens
        
        Args:
            data (array): Input seismogram
            sampling_rate (float): Sampling frekvens i Hz  
            corner_freq (float): Corner frekvens i Hz
            order (int, optional): Filter orden
            
        Returns:
            array: Lavpas filtreret data
        """
        try:
            if order is None:
                order = self.filter_order
                
            nyquist = sampling_rate / 2.0
            corner_norm = corner_freq / nyquist
            
            if corner_norm <= 0 or corner_norm >= 1:
                return data
                
            b, a = butter(order, corner_norm, btype='low')
            return filtfilt(b, a, data)
            
        except Exception as e:
            print(f"Lavpas filter fejl: {e}")
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
    
    def process_waveform_with_filtering(self, waveform_data, filter_type='broadband', 
                                      remove_spikes=True, calculate_noise=True):
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
    
    def get_filter_summary(self, processed_data):
        """
        Genererer resumé af udførte filter operationer til brugerfeedback.
        
        Args:
            processed_data (dict): Output fra process_waveform_with_filtering
            
        Returns:
            dict: Opsummering af processing resultater
        """
        try:
            summary = {
                'filter_applied': processed_data.get('filter_used', 'none'),
                'filter_params': processed_data.get('filter_params'),
                'components_processed': list(processed_data.get('filtered_data', {}).keys()),
                'spikes_removed': {},
                'noise_levels': {},
                'max_snr': {}
            }
            
            # Opsummér spike fjernelse for hver komponent
            for component, spike_info in processed_data.get('spike_info', {}).items():
                summary['spikes_removed'][component] = {
                    'count': spike_info.get('num_spikes', 0),
                    'percentage': spike_info.get('spike_percentage', 0)
                }
            
            # Opsummér støj niveauer
            for component, noise_stats in processed_data.get('noise_stats', {}).items():
                summary['noise_levels'][component] = noise_stats.get('rms', 0)
            
            # Find maksimale SNR værdier
            for component, snr_data in processed_data.get('snr_data', {}).items():
                if len(snr_data.get('snr_db', [])) > 0:
                    summary['max_snr'][component] = np.max(snr_data['snr_db'])
                else:
                    summary['max_snr'][component] = None
            
            return summary
            
        except Exception as e:
            print(f"Filter resumé fejl: {e}")
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
    
    def fetch_latest_earthquakes(self, min_magnitude=6.5, limit=25):
        """
        Henter seneste jordskælv fra IRIS catalog med intelligent søgestrategi.
        
        Implementerer progressiv søgning der starter med nylige events og
        udvider bagud i tid indtil tilstrækkelige jordskælv findes.
        Dette optimerer for både aktualitet og resultat kvalitet.
        
        Args:
            min_magnitude (float): Minimum magnitude threshold (default: 6.5)
            limit (int): Maksimum antal jordskælv at returnere (default: 25)
            
        Returns:
            list: Liste af jordskælv dictionaries med komplet metadata
            
        Note:
            Søgestrategi:
            1. Start med 30 dage tilbage (nyeste events)
            2. Udvid progressivt til max 20 år
            3. Stop når limit nået eller ingen flere events
            4. Sortér efter tid (nyeste først)
            
        Example:
            earthquakes = manager.fetch_latest_earthquakes(min_magnitude=7.0, limit=10)
            for eq in earthquakes:
                print(f"M{eq['magnitude']:.1f} - {eq['description']}")
        """
        if not self.client:
            return []
        
        try:
            # Progressiv søgestrategi - start med nylige events
            search_periods = [30, 90, 180, 365, 730, 1095, 1825, 2555, 3650, 5475, 7300]  # dage
            all_earthquakes = []
            
            progress_placeholder = st.empty()
            
            # Søg progressivt bagud i tid
            for days_back in search_periods:
                progress_placeholder.info(f"🔍 Søger {days_back} dage tilbage...")
                
                # Definer søge tidsvindue
                end_time = UTCDateTime.now()
                start_time = end_time - (days_back * 86400)  # Konverter dage til sekunder
                
                try:
                    # Forespørg IRIS event catalog
                    catalog = self.client.get_events(
                        starttime=start_time,
                        endtime=end_time,
                        minmagnitude=min_magnitude,
                        orderby="time-asc",  # Tidssorteret
                        limit=500  # Høj limit for at få alle relevante events
                    )
                    
                    if len(catalog) > 0:
                        # Processer og validér fundne events
                        earthquakes = self._process_catalog(catalog)
                        
                        # Check om vi har nok events til at stoppe søgning
                        if len(earthquakes) >= limit:
                            earthquakes.sort(key=lambda x: x['time'], reverse=True)  # Nyeste først
                            final_earthquakes = earthquakes[:limit]
                            
                            progress_placeholder.empty()
                            return final_earthquakes
                        else:
                            all_earthquakes = earthquakes
                
                except Exception as search_error:
                    # Fortsæt til næste søgeperiode ved fejl
                    continue
            
            # Returner hvad vi fandt, selvom det ikke er det fulde limit
            progress_placeholder.empty()
            if len(all_earthquakes) > 0:
                all_earthquakes.sort(key=lambda x: x['time'], reverse=True)
                return all_earthquakes
            else:
                return []
            
        except Exception as e:
            return []
    
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
    
    def find_stations_for_earthquake(self, earthquake, min_distance_km=800, max_distance_km=2200, target_stations=4):
        """
        Finder optimal stationer til seismisk analyse med intelligent udvælgelse.
        
        Søger efter 4 analyse-klar stationer i optimal teleseismisk afstand (800-2200 km).
        Bruger prioriterede netværk og geografisk distribution for bedste analyse kvalitet.
        
        Args:
            earthquake (dict): Jordskælv metadata
            min_distance_km (int): Minimum afstand - undgår direkte bølger (default: 800)
            max_distance_km (int): Maksimum afstand - før core shadow zone (default: 2200)
            target_stations (int): Ønsket antal stationer (default: 4)
            
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
        Optimeret fallback til kurateret liste af analyse-klar stationer.
        
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
            Kurateret liste fokuserer på:
            - IU/II GSN stationer (højeste prioritet)
            - G GEOSCOPE stationer (høj kvalitet)
            - Kendte pålidelige regionale stationer
            - Geografisk distribution på globalt niveau
            
        Example:
            fallback = manager._fallback_station_list_optimized(eq, 800, 2200, 4)
        """
        eq_lat = earthquake['latitude']
        eq_lon = earthquake['longitude']
        eq_depth = earthquake['depth_km']
        
        # Hånd-kurateret liste af pålidelige analyse stationer
        # Baseret på årelang erfaring med data kvalitet og tilgængelighed
        analysis_ready_stations = [
            # Europa - Høj kvalitets bredband stationer
            {'net': 'IU', 'sta': 'KONO', 'lat': 59.65, 'lon': 9.60},    # Norge
            {'net': 'II', 'sta': 'BFO', 'lat': 48.33, 'lon': 8.33},     # Tyskland
            {'net': 'G', 'sta': 'SSB', 'lat': 45.28, 'lon': 4.54},      # Frankrig
            {'net': 'IU', 'sta': 'KIEV', 'lat': 50.70, 'lon': 29.22},   # Ukraine
            {'net': 'GE', 'sta': 'WLF', 'lat': 49.66, 'lon': 6.15},     # Tyskland
            
            # Nordamerika - GSN stationer
            {'net': 'IU', 'sta': 'ANMO', 'lat': 34.95, 'lon': -106.46}, # New Mexico
            {'net': 'IU', 'sta': 'HRV', 'lat': 42.51, 'lon': -71.56},   # Harvard
            {'net': 'IU', 'sta': 'COLA', 'lat': 64.87, 'lon': -147.86}, # Alaska
            {'net': 'US', 'sta': 'LRAL', 'lat': 39.88, 'lon': -77.45},  # Virginia
            {'net': 'IU', 'sta': 'CCM', 'lat': 38.06, 'lon': -91.24},   # Missouri
            
            # Asien-Pacific - Pålidelige bredband stationer
            {'net': 'IU', 'sta': 'MAJO', 'lat': 36.54, 'lon': 138.20},  # Japan
            {'net': 'IU', 'sta': 'INCN', 'lat': 37.48, 'lon': 126.62},  # Sydkorea
            {'net': 'II', 'sta': 'KURK', 'lat': 50.71, 'lon': 78.62},   # Kasakhstan
            {'net': 'IU', 'sta': 'ULN', 'lat': 47.87, 'lon': 107.05},   # Mongoliet
            {'net': 'IU', 'sta': 'CHTO', 'lat': 18.81, 'lon': 98.98},   # Thailand
            
            # Australien/Oceanien
            {'net': 'G', 'sta': 'CAN', 'lat': -35.32, 'lon': 149.00},   # Australien
            {'net': 'IU', 'sta': 'CTAO', 'lat': -20.09, 'lon': 146.25}, # Australien
            {'net': 'II', 'sta': 'WRAB', 'lat': -19.93, 'lon': 134.36}, # Australien
            {'net': 'IU', 'sta': 'NWAO', 'lat': -32.93, 'lon': 117.24}, # Australien
            
            # Sydamerika
            {'net': 'IU', 'sta': 'SAML', 'lat': -8.95, 'lon': -63.18},  # Brasilien
            {'net': 'IU', 'sta': 'LPAZ', 'lat': -16.29, 'lon': -68.13}, # Bolivia
            {'net': 'IU', 'sta': 'RCBR', 'lat': -5.82, 'lon': -35.90},  # Brasilien
            
            # Afrika/Mellemøsten
            {'net': 'G', 'sta': 'TAM', 'lat': 22.79, 'lon': 5.53},      # Algeriet
            {'net': 'II', 'sta': 'MSEY', 'lat': -4.67, 'lon': 55.48},   # Seychellerne
            {'net': 'II', 'sta': 'ASCN', 'lat': -7.93, 'lon': -14.36}   # Ascension Island
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
        Henter waveform data med korrekt timing validering og korrektion.
        
        Kritisk funktion der henter 30 minutters seismisk data fra IRIS
        med præcis timing alignment til jordskælv oprindelsestid. Implementerer
        robust fejlhåndtering og automatisk channel prioritering.
        
        Args:
            earthquake (dict): Jordskælv med ObsPy event objekt
            station (dict): Station metadata med netværk og position
            
        Returns:
            dict or None: Komplet waveform data struktur eller None ved fejl
                Returneret struktur indeholder:
                - 'time': Tid array relativ til jordskælv (sekunder)
                - 'sampling_rate': Data sampling frekvens (Hz)
                - 'raw_data': Instrument counts (original enheder)
                - 'displacement_data': Kalibreret displacement (mm)
                - 'timing_offset': Detekteret timing korrektion
                - 'timing_validation': Fysisk realistisk vurdering
                
        Note:
            Timing er KRITISK for seismisk analyse:
            - Data starter præcis ved jordskælv tid (ikke station tid)
            - 30 minutters varighed fanger alle relevante faser
            - Automatisk korrektion for data/event timing forskelle
            - Validering af P-bølge hastigheder (5.8-13.7 km/s)
            
        Channel Priority:
            1. HH* - High sample rate, high gain (100 Hz)
            2. BH* - Broadband, high gain (20-40 Hz)  
            3. LH* - Long period, high gain (1 Hz)
            4. *H* - Any high gain channels
            5. *N*,*E*,*Z* - Fallback til enhver orientering
            
        Example:
            waveform = manager.download_waveform_data(earthquake, station)
            if waveform:
                print(f"Data: {len(waveform['time'])} samples @ {waveform['sampling_rate']} Hz")
                print(f"Timing offset: {waveform['timing_offset']:.1f} seconds")
        """
        if not self.client:
            return None
        
        try:
            # Hent præcis jordskælv tidspunkt fra ObsPy event
            eq_time = earthquake['obspy_event'].preferred_origin().time
            
            # KRITISK: Start data præcis ved jordskælv tid, ikke station lokal tid
            start_time = eq_time  # Ingen offset - præcis timing
            end_time = eq_time + 1800  # 30 minutter (1800 sekunder)
            
            # Bruger feedback til langsom IRIS download
            progress = st.empty()
            progress.info(f"📡 Henter data...")
            
            # Prioriteret channel liste - højeste sampling rate først
            # Dette sikrer bedst mulig data kvalitet til analyse
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
                        sample_rate = waveform[0].stats.sampling_rate
                        progress.success(f"✅ Data hentet ({sample_rate} Hz)")
                        break  # Stop ved første succesfulde download
                        
                except Exception:
                    continue  # Prøv næste channel type
            
            # Validér at data blev hentet
            if waveform is None or len(waveform) == 0:
                progress.error(f"❌ Ingen data tilgængelig")
                return None
            
            # TIMING VALIDERING: Tjek data start tid mod jordskælv tid
            first_trace = waveform[0]
            data_start_time = first_trace.stats.starttime
            time_offset = float(data_start_time - eq_time)
            
            # Vis kun timing advarsler hvis signifikant offset
            if abs(time_offset) > 10:  # Mere end 10 sekunder
                progress.warning(f"⚠️ Timing justeret: {time_offset:.1f}s offset")
            
            # Processer waveform med timing korrektion
            processed_data = self._process_real_waveform_FIXED(
                waveform, earthquake, station, used_channels, time_offset
            )
            
            if processed_data:
                # Tilføj timing metadata til output
                processed_data['timing_offset'] = time_offset
                processed_data['data_start_utc'] = data_start_time.strftime('%Y-%m-%d %H:%M:%S')
                processed_data['earthquake_utc'] = eq_time.strftime('%Y-%m-%d %H:%M:%S')
                
                # Fysisk timing validering - advarer kun ved problemer
                is_valid, validation_message, validation_info = self.processor.validate_earthquake_timing(
                    earthquake, station, processed_data
                )
                
                processed_data['timing_validation'] = {
                    'is_valid': is_valid,
                    'message': validation_message,
                    'info': validation_info
                }
                
                # Vis kun timing problemer hvis de eksisterer
                if not is_valid:
                    expected_range = validation_info['realistic_p_range']
                    progress.warning(f"⚠️ {validation_message}")
                    st.info(f"💡 Forventet: {expected_range[0]:.1f}-{expected_range[1]:.1f}s")
            
            return processed_data
                
        except Exception as e:
            st.error(f"❌ Download fejl: {e}")
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
    
    Streamlit-baseret web interface der kombinerer:
    - Interactive verdenskort med jordskælv og stationer
    - Real-time data hentning fra IRIS
    - Avanceret seismisk analyse med multiple visualiseringer
    - Brugervenlig kontrol panel til filter og indstillinger
    - Excel eksport til professionel rapportering
    
    Denne klasse fungerer som central koordinator mellem data management,
    signal processing og bruger interface komponenter.
    """
    
    def __init__(self):
        """
        Initialiserer hovedapplikation med session state og data manager.
        
        Opsætter:
        - Streamlit session state management
        - IRIS data manager forbindelse
        - Automatic jordskælv data loading
        """
        self.setup_session_state()
        self.data_manager = StreamlinedDataManager()
        self.initialize_app()
        # Velkomst sektion med gradient baggrund
        with st.sidebar:
            st.markdown("---")
            st.markdown("""
            <h2 style='color: #1f77b4; margin-bottom: 20px;'>🌍 GEOseis</h2>
            </div>
            """, unsafe_allow_html=True)
            st.caption("""
            **FEATURES:**
            - Real-time jordskælv data fra IRIS  
            - Professionel signal processering  
            - Ms magnitude beregning  
            - Interaktive visualiseringer  
            - Excel eksport til undervisningen
            """)
            st.markdown("---")
            st.caption("""
            **SÅDAN GØR DU:**
            1. Justér skyder for de nyeste 25 jordskælv
            2. Klik på et jordskælv på kortet
            2. Vælg en analyse-klar station 
            3. Rul ned og se analysen
            4. Juster filter indstillinger
            5. Eksporter til Excel
            """)
            
            st.markdown("---")
            st.caption("🌍 **Udviklet af:** Philip Kruse Jakobsen")

    
    def setup_session_state(self):
        """
        Opsætter Streamlit session state med standard værdier.
        
        Session state håndterer persistent data på tværs af bruger interaktioner:
        - earthquake_df: DataFrame med tilgængelige jordskælv
        - selected_earthquake: Aktuel valgt jordskælv  
        - station_list: Stationer tilgængelige for valgt jordskælv
        - selected_station: Aktuel valgt station
        - waveform_data: Hentet seismisk data
        - component_visibility: Kontrol af N/E/Z komponent visning
        - analysis_results: Cached analyse resultater
        
        Note:
            Session state bevares mellem Streamlit reruns og giver
            kontinuerlig brugeroplevelse uden data tab.
        """
        defaults = {
            'earthquake_df': pd.DataFrame(),
            'selected_earthquake': None,
            'station_list': [],
            'selected_station': None,
            'waveform_data': None,
            'analysis_results': {},
            'magnitude_threshold': 6.5,  # Standard minimum magnitude
            'data_loaded': False,
            'show_stations': False,
            'show_analysis': False,
            'component_visibility': {'north': True, 'east': True, 'vertical': True}  # Default alle komponenter synlige
        }
        
        # Initialisér kun hvis ikke allerede sat
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value
    
    def initialize_app(self):
        """
        Initialiserer applikation med header og initial data loading.
        
        Viser brugervenlig header og starter automatisk data loading
        hvis ikke allerede udført.
        """
        st.markdown("## 🌍 GEOseis")
        st.markdown("**Overskuelig seismisk analyse med Excel-eksport til undervisningen**")
        # Automatisk data loading ved første besøg
        if not st.session_state.data_loaded:
            with st.spinner("🔍 Indlæser jordskælv..."):
                self.load_initial_data()
    
    def load_initial_data(self):
        try:
            earthquakes = self.data_manager.fetch_latest_earthquakes(
            min_magnitude=st.session_state.magnitude_threshold,
            limit=25
            )
        
            if earthquakes:
                df = pd.DataFrame(earthquakes)
                st.session_state.earthquake_df = df
                st.session_state.data_loaded = True
            else:
                st.error("❌ Ingen jordskælv fundet. Prøv at sænke magnitude threshold.")
            
        except Exception as e:
            st.error(f"❌ Kunne ikke forbinde til IRIS server: {e}")
            st.info("💡 Tjek din internetforbindelse og prøv igen")
            st.session_state.data_loaded = False

    def get_earthquake_color_and_size(self, magnitude):
        """
        Bestemmer farve og størrelse for jordskælv markører baseret på magnitude.
        
        Bruger standard seismologisk farveskala for intuitivt interface:
        - Større jordskælv = varmere farver (rød)
        - Mindre jordskælv = køligere farver (grøn)
        - Markør størrelse skalerer med magnitude
        
        Args:
            magnitude (float): Jordskælv magnitude
            
        Returns:
            tuple: (color, size) for Folium markør
            
        Scale:
            M≥8.0: Meget store jordskælv (darkred, 15px)
            M7.5-7.9: Store jordskælv (red, 12px)
            M7.0-7.4: Kraftige jordskælv (orange, 10px)
            M6.5-6.9: Moderate jordskælv (yellow, 8px)
            M<6.5: Små jordskælv (green, 6px)
        """
        if magnitude >= 8.0:
            return 'darkred', 15
        elif magnitude >= 7.5:
            return 'red', 12
        elif magnitude >= 7.0:
            return 'orange', 10
        elif magnitude >= 6.5:
            return 'yellow', 8
        else:
            return 'green', 6
    def create_optimized_map(self, earthquakes_df, stations=None):
        """
        Opretter optimeret Folium kort med automatisk zoom og intelligente markører.
        """
        if earthquakes_df.empty:
            return None
        
        # Intelligent bounds beregning baseret på data og selection
        selected_eq = st.session_state.get('selected_earthquake')
        
        if stations and st.session_state.get('show_stations', False) and selected_eq:
            # Fokusér på jordskælv + stationer når begge er valgt
            eq_lat, eq_lon = selected_eq['latitude'], selected_eq['longitude']
            station_lats = [s['latitude'] for s in stations]
            station_lons = [s['longitude'] for s in stations]
            
            # Kombiner alle koordinater til bounds beregning
            all_lats = [eq_lat] + station_lats
            all_lons = [eq_lon] + station_lons
            
            lat_min, lat_max = min(all_lats), max(all_lats)
            lon_min, lon_max = min(all_lons), max(all_lons)
            
            # Intelligent padding baseret på distribution
            lat_range = lat_max - lat_min
            lon_range = lon_max - lon_min
            
            if lat_range < 5 and lon_range < 5:
                padding = max(2.0, max(lat_range, lon_range) * 0.5)
                zoom_start = 5
            elif lat_range < 15 and lon_range < 15:
                padding = max(lat_range, lon_range) * 0.3
                zoom_start = 4
            else:
                padding = max(lat_range, lon_range) * 0.15
                zoom_start = 3
            
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            
            # Manuel zoom til stationer
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=zoom_start,
                tiles='Esri_WorldImagery',
                attr=' '
            )
            
            # Anvend bounds for stationer
            southwest = [lat_min - padding, lon_min - padding]
            northeast = [lat_max + padding, lon_max + padding]
            m.fit_bounds([southwest, northeast], padding=(30, 30))
            
        else:
            # INITIAL VIEW: Beregn automatisk zoom til alle jordskælv
            lat_min, lat_max = earthquakes_df['latitude'].min(), earthquakes_df['latitude'].max()
            lon_min, lon_max = earthquakes_df['longitude'].min(), earthquakes_df['longitude'].max()
            
            # Beregn optimal centrum
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            
            # Beregn automatisk zoom niveau baseret på spredning
            lat_range = lat_max - lat_min
            lon_range = lon_max - lon_min
            max_range = max(lat_range, lon_range)
            
            # Intelligent zoom baseret på spredning
            if max_range > 120:  # Global spredning
                zoom_start = 2
            elif max_range > 60:  # Continental spredning  
                zoom_start = 3
            elif max_range > 30:  # Regional spredning
                zoom_start = 4
            elif max_range > 15:  # Lokal spredning
                zoom_start = 5
            else:  # Meget lokal spredning
                zoom_start = 6
            
            # Opret kort med beregnet zoom
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=zoom_start,
                tiles='Esri_WorldImagery',
                attr=' '
            )
        
        # Tilføj jordskælv markører med stjerne for valgt jordskælv
        for idx, eq in earthquakes_df.iterrows():
            color, radius = self.get_earthquake_color_and_size(eq['magnitude'])
            
            # Check om dette jordskælv er valgt
            is_selected = (st.session_state.get('selected_earthquake') and 
                        st.session_state.selected_earthquake['index'] == eq['index'])
            
            if is_selected:
                # STJERNE MARKØR for valgt jordskælv
                star_html = f"""
                <div style="
                    color: gold;
                    font-size: {radius + 20}px;
                    text-align: center;
                    line-height: 1;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
                    filter: drop-shadow(0 0 3px rgba(255,215,0,0.8));
                ">⭐</div>
                """
                
                folium.Marker(
                    location=[eq['latitude'], eq['longitude']],
                    icon=folium.DivIcon(
                        html=star_html,
                        icon_size=(radius + 15, radius + 15),
                        icon_anchor=((radius + 15)//2, (radius + 15)//2)
                    ),
                    tooltip=f"✅ VALGT: M{eq['magnitude']:.1f} - {eq['time'].strftime('%d %b %Y')}",
                    popup=f"⭐ VALGT JORDSKÆLV ⭐<br>M {eq['magnitude']:.1f}<br>{eq['time'].strftime('%d %b %Y %H:%M')}<br>Lat: {eq['latitude']:.2f}, Lon: {eq['longitude']:.2f}"
                ).add_to(m)
                
            else:
                # NORMAL CIRKEL MARKØR for ikke-valgte jordskælv
                folium.CircleMarker(
                    location=[eq['latitude'], eq['longitude']],
                    radius=radius + 3,
                    tooltip=f"M{eq['magnitude']:.1f} - {eq['time'].strftime('%d %b %Y')} (Klik for stationer)",
                    color='black',
                    opacity=0.4,
                    fillColor=color,
                    fillOpacity=0.8,
                    weight=2,
                    popup=f"M{eq['magnitude']:.1f} - {eq['time'].strftime('%d %b %Y')}"
                ).add_to(m)
        
        # Tilføj station markører som nummererede trekanter
        if stations and st.session_state.get('show_stations', False):
            for i, station in enumerate(stations):
                station_id = i + 1
                
                # Fremhæv valgt station
                if (st.session_state.get('selected_station') and 
                    st.session_state.selected_station['station'] == station['station']):
                    triangle_color = 'darkred'
                    text_color = 'white'
                else:
                    triangle_color = 'blue'
                    text_color = 'white'
                
                # CSS til custom trekant markør med nummer
                triangle_html = f"""
                <div style="
                    width: 0; 
                    height: 0; 
                    border-left: 12px solid transparent;
                    border-right: 12px solid transparent;
                    border-bottom: 20px solid {triangle_color};
                    position: relative;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                ">
                    <div style="
                        position: absolute;
                        top: 6px;
                        left: -6px;
                        color: {text_color};
                        font-weight: bold;
                        font-size: 10px;
                        text-align: center;
                        width: 12px;
                    ">{station_id}</div>
                </div>
                """
                
                # Tooltip med data kvalitets information
                source_info = station.get('data_source', 'UNKNOWN')
                tooltip_text = f"Station {station_id}: {station['network']}.{station['station']} ({station['distance_km']:.0f} km)"
                if source_info == 'IRIS_INVENTORY':
                    tooltip_text += " ✅ IRIS Verified"
                elif source_info == 'FALLBACK_LIST':
                    tooltip_text += " ⚠️ Fallback List"
                
                # Tilføj custom marker
                folium.Marker(
                    location=[station['latitude'], station['longitude']],
                    icon=folium.DivIcon(
                        html=triangle_html,
                        icon_size=(24, 20),
                        icon_anchor=(12, 20)
                    ),
                    tooltip=tooltip_text
                ).add_to(m)
        
        # Tilføj professionel magnitude legend - EFTER kort er færdigt
        legend_html = '''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 100px; height: 180px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px; border-radius: 5px;
                    box-shadow: 0 0 15px rgba(0,0,0,0.2);">
        <p style="margin: 0; font-weight: bold; text-align: center; font-size: 14px;">Magnitude</p>
        <hr style="margin: 4px 0;">
        <p style="margin: 2px 0;"><span style="color: darkred; font-size: 18px;">●</span> M ≥ 8.0 </p>
        <p style="margin: 2px 0;"><span style="color: red; font-size: 16px;">●</span> M 7.5-7.9 </p>
        <p style="margin: 2px 0;"><span style="color: orange; font-size: 14px;">●</span> M 7.0-7.4 </p>
        <p style="margin: 2px 0;"><span style="color: #DAA520; font-size: 12px;">●</span> M 6.5-6.9 </p>
        <p style="margin: 2px 0;"><span style="color: green; font-size: 10px;">●</span> M < 6.5 </p>
        <p style="margin: 2px 0;"><span style="color: gold; font-size: 14px;">⭐</span> Valgt</p>
        <hr style="margin: 5px 0;">
        </div>
        '''
        
        # Tilføj legend til kort - HELT til sidst
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
    
    def process_earthquake_click(self, clicked_lat, clicked_lon, earthquakes_df):
        """
        Processerer bruger klik på jordskælv markører med intelligent matching.
        
        Finder nærmeste jordskælv til klik position og håndterer selection logic.
        Implementerer intelligent afstands threshold og automatic station loading.
        
        Args:
            clicked_lat (float): Klik latitude
            clicked_lon (float): Klik longitude  
            earthquakes_df (DataFrame): Tilgængelige jordskælv
            
        Returns:
            bool: True hvis valid earthquake selection, False ellers
            
        Note:
            - Bruger euklidisk afstand for hurtighed (acceptable for kort zoom)
            - 3.0 grad threshold for click tolerance 
            - Automatisk station loading ved ny selection
            - Toggle behavior for allerede valgte jordskælv
        """
        try:
            closest_eq = None
            min_distance = float('inf')
            
            # Find nærmeste jordskælv til klik position
            for _, eq in earthquakes_df.iterrows():
                # Simpel euklidisk afstand (acceptable for zoom levels brugt)
                distance = ((eq['latitude'] - clicked_lat)**2 + (eq['longitude'] - clicked_lon)**2)**0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_eq = eq.to_dict()
            
            # Kontroller om klik er tæt nok på et jordskælv
            if closest_eq and min_distance < 3.0:  # 3 grad tolerance
                current_eq = st.session_state.get('selected_earthquake')
                
                # Check om dette er en ny selection
                if not current_eq or current_eq['index'] != closest_eq['index']:
                    # Ny jordskælv valgt - reset alt relateret state
                    st.session_state.selected_earthquake = closest_eq
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.session_state.show_analysis = False
                    st.session_state.station_list = []
                    st.session_state.show_stations = False
                    
                    # Start automatisk station søgning
                    new_stations = self.data_manager.find_stations_for_earthquake(closest_eq)
                    if new_stations:
                        st.session_state.station_list = new_stations
                        st.session_state.show_stations = True
                    
                    return True
                else:
                    # Samme jordskælv klikket igen - toggle station visning
                    if not st.session_state.get('show_stations', False):
                        st.session_state.show_stations = True
                    return True
            
            return False
            
        except Exception:
            return False
    
    def handle_earthquake_click(self, map_data, earthquakes_df):
        """
        Håndterer jordskælv klik detektion fra Folium kort.
        
        Parser Streamlit-Folium return data for at detektere bruger klik
        på jordskælv markører og trigger appropriate actions.
        
        Args:
            map_data (dict): Return data fra st_folium
            earthquakes_df (DataFrame): Tilgængelige jordskælv
            
        Returns:
            bool: True hvis valid klik detekteret og processeret
            
        Note:
            Håndterer både object clicks og general map clicks
            for maksimal bruger responsiveness.
        """
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
    
    def create_main_interface(self):
        """
        Opretter hovedbrugerinterface med kort og kontrol panel.
        
        Implementerer responsive 2-kolonne layout:
        - Venstre: Interaktivt Folium kort med jordskælv og stationer
        - Højre: Kontrol panel med magnitude slider og station selection
        
        Features:
        - Real-time earthquake/station click detection
        - Automatic magnitude filtering med data reload
        - Station quality indicators (IRIS verified vs fallback)
        - Progressive disclosure (kun vis relevante kontroller)
        - Status feedback til bruger guidance
        """
        df = st.session_state.earthquake_df
        if df.empty:
            if st.session_state.data_loaded == False:
                st.warning("⚠️ Ingen jordskælv data tilgængelig")
                if st.button("🔄 Prøv igen"):
                    self.load_initial_data()
                    st.rerun()
            return
        
        
        # Responsive 2-kolonne layout
        col1, col2 = st.columns([3, 1])  # 60/40 split for optimal balance
        
        with col1:
            # Generer kort med current earthquake/station state
            stations = st.session_state.get('station_list', []) if st.session_state.get('show_stations', False) else []
            earthquake_map = self.create_optimized_map(df, stations)
            
            if earthquake_map is not None:
                map_container = st.container()
                with map_container:
                    # Render interaktivt kort med click detection
                    map_data = st_folium(
                        earthquake_map, 
                        width=950, 
                        height=650,
                        returned_objects=["last_object_clicked", "last_clicked"],
                        key="main_map"
                    )
                
                # Processer alle typer af klik events
                click_detected = self._process_map_clicks(map_data, df)
                if click_detected:
                    st.rerun()  # Trigger UI update efter selection change
        
        with col2:
            # Magnitude threshold kontrol med automatic reload
            new_magnitude = st.slider(
                "Min. Magnitude",
                min_value=5.0,
                max_value=8.0,
                value=st.session_state.magnitude_threshold,
                step=0.1,
                key="mag_slider",
                help="Højere værdi = kraftigere jordskælv"
            )
            
            # Check for magnitude change og reload data hvis nødvendigt
            if new_magnitude != st.session_state.magnitude_threshold:
                st.session_state.magnitude_threshold = new_magnitude
                # Reset all state ved magnitude change
                st.session_state.data_loaded = False
                st.session_state.selected_earthquake = None
                st.session_state.selected_station = None
                st.session_state.show_stations = False
                st.session_state.show_analysis = False
                st.session_state.waveform_data = None
                st.session_state.station_list = []
                self.load_initial_data()
                st.rerun()
            
            # Dynamic status feedback baseret på current state
            if st.session_state.get('show_analysis'):
                st.markdown("**🟢 Analyse klar**")
            elif st.session_state.get('selected_earthquake'):
                selected_eq = st.session_state.get('selected_earthquake')
                st.markdown(f"**🟡 M{selected_eq['magnitude']:.1f} - {selected_eq['time'].strftime('%d %b %Y')} | {selected_eq['depth_km']:.1f} km dybde**")
                st.markdown("**Vælg en analyse-klar station:**")
            else:
                st.markdown("**🔴 Klik på et jordskælv på kortet**")
            
            st.markdown("---")
            
            # Station selection interface (kun vis når relevant)
            selected_eq = st.session_state.get('selected_earthquake')
            selected_station = st.session_state.get('selected_station')
            stations = st.session_state.get('station_list', [])
            
            if selected_eq and stations:
                # Station kvalitets information
                iris_verified = sum(1 for s in stations if s.get('data_source') == 'IRIS_INVENTORY')
                fallback_count = len(stations) - iris_verified
                
                st.info(f"🎯 **{len(stations)} analyse-klar stationer** (800-2200 km)")
                if iris_verified > 0:
                    st.success(f"✅ {iris_verified} IRIS verificerede")
                if fallback_count > 0:
                    st.info(f"ℹ️ {fallback_count} fallback stationer")
                
                # Station selection knapper med kvalitets indikatorer
                for i, station in enumerate(stations):
                    station_id = i + 1
                    is_selected = selected_station and station['station'] == selected_station['station']
                    
                    # Data kvalitets indikator
                    source_indicator = "✅" if station.get('data_source') == 'IRIS_INVENTORY' else "📊"
                    button_color = "🔴" if is_selected else "🔵"
                    button_text = f"{button_color} {station_id}: {station['network']}.{station['station']} ({station['distance_km']:.0f}km) {source_indicator}"
                    
                    # Station selection handling
                    if st.button(button_text, key=f"analysis_station_{i}", use_container_width=True):
                        # Reset analysis state for ny station
                        st.session_state.waveform_data = None
                        st.session_state.show_analysis = False
                        st.session_state.selected_station = station
                        
                        # Download data med user feedback
                        with st.spinner(f"📡 Henter analyse data fra {station['network']}.{station['station']}..."):
                            waveform_data = self.data_manager.download_waveform_data(selected_eq, station)
                            
                            if waveform_data:
                                st.session_state.waveform_data = waveform_data
                                st.session_state.show_analysis = True
                                st.success(f"✅ Analyse klar! Komponenter: {', '.join(waveform_data.get('available_components', []))}")
                                
                                # Vis kun timing problemer hvis de eksisterer
                                if 'timing_validation' in waveform_data:
                                    validation = waveform_data['timing_validation']
                                    if not validation['is_valid']:
                                        st.warning(f"⚠️ Timing problem: {validation['message']}")
                                        if validation['info']:
                                            info = validation['info']
                                            expected_range = info['realistic_p_range']
                                            st.info(f"💡 Forventet P-ankomst: {expected_range[0]:.1f} - {expected_range[1]:.1f}s")
                                
                                st.rerun()
                            else:
                                st.error("❌ Ingen data kunne hentes")
                                st.session_state.selected_station = None
            else:
                if selected_eq:
                    st.info("🔍 Ingen analyse-klar stationer fundet for dette jordskælv")
                # Vis summary statistik når ingen selection
                st.metric("Tilgængelige jordskælv", f"{len(df)}")
    
    def _process_map_clicks(self, map_data, df):
        """
        Centraliseret håndtering af alle map click events.
        
        Processerer både object clicks og general clicks fra Folium kort
        for at maksimere click detection reliability.
        
        Args:
            map_data (dict): Folium return data
            df (DataFrame): Earthquake data
            
        Returns:
            bool: True hvis nogen click blev processeret
        """
        if not map_data:
            return False
            
        click_detected = False
        
        # Håndter object clicks (prioriteret)
        if map_data.get("last_object_clicked"):
            try:
                clicked_obj = map_data["last_object_clicked"]
                if clicked_obj and isinstance(clicked_obj, dict):
                    if "lat" in clicked_obj and "lng" in clicked_obj:
                        clicked_lat = clicked_obj["lat"]
                        clicked_lon = clicked_obj["lng"]
                        click_detected = self.process_earthquake_click(clicked_lat, clicked_lon, df)
            except:
                pass
        
        # Håndter general clicks som fallback
        if not click_detected and map_data.get("last_clicked"):
            try:
                if self.handle_earthquake_click(map_data, df):
                    click_detected = True
            except:
                pass
        
        return click_detected
    
    
    def create_enhanced_analysis_window(self):
        """
        Opretter avanceret analyse vindue med komplet seismisk analyse suite.
        
        Implementerer professionel seismisk analyse interface med:
        - Filter kontrol panel med 7 forskellige filter typer
        - Avancerede visualiserings optioner (SNR, FFT, P-wave analysis)
        - Real-time Ms magnitude beregning med IASPEI standarder
        - Excel eksport funktionalitet
        - Multi-panel Plotly visualisering med intelligent layout
        - Comprehensive user guidance og quality feedback
        
        Dette er hjerte af seismisk analyse funktionaliteten.
        """
        selected_eq = st.session_state.get('selected_earthquake')
        selected_station = st.session_state.get('selected_station')
        waveform_data = st.session_state.get('waveform_data')
        
        # Kræv alle kritiske komponenter før visning
        if not all([selected_eq, selected_station, waveform_data]):
            return
        
        st.markdown("---")
        st.markdown(f"**📈 Analyse: {selected_station['network']}.{selected_station['station']}**")
        
        # Vis kun timing problemer hvis de eksisterer
        if 'timing_validation' in waveform_data:
            validation = waveform_data['timing_validation']
            if not validation['is_valid']:
                st.warning(f"⚠️ {validation['message']}")
                if validation['info']:
                    info = validation['info']
                    expected_range = info['realistic_p_range']
                    st.info(f"💡 Forventet: {expected_range[0]:.1f}-{expected_range[1]:.1f}s (observeret: {info['p_arrival_time']:.1f}s)")
        
        # Bruger guide toggle
        col_info, col_space = st.columns([1, 4])
        with col_info:
            if st.button("ℹ️ Bruger Guide", key="info_button"):
                st.session_state['show_user_guide'] = not st.session_state.get('show_user_guide', False)
        
        # Expandable user guide med technical details
        if st.session_state.get('show_user_guide', False):
            with st.expander("📚 GEOseis Analyse Guide", expanded=True):
                # Show current data specifications
                sampling_rate = waveform_data.get('sampling_rate', 'Ukendt')
                nyquist_freq = sampling_rate / 2.0 if isinstance(sampling_rate, (int, float)) else 'Ukendt'
                
                st.info(f"**Aktuel Data:** Sampling rate: {sampling_rate} Hz | Nyquist frekvens: {nyquist_freq} Hz")
                st.info(f"**⏰ Timing:** Tid 0s = Jordskælv tidspunkt | Data længde: 30 minutter")
                
                # Comprehensive filter guide
                st.markdown("""
                **🎛️ Filter Typer:**
                - **🔹 Ingen filtrering**: Originale data som hentet fra IRIS (kun response fjernelse)
                - **🔹 Bredband**: Standard filter, fjerner mest støj (0.01-25 Hz)
                - **🔹 P-bølger**: Isolerer primære kompressionsbølger (1.0-10 Hz)
                - **🔹 S-bølger**: Isolerer sekundære forskydningsbølger (0.5-5.0 Hz)  
                - **🔹 Overfladebølger**: ✅ **Bedst til Ms magnitude beregning** (0.02-0.5 Hz)
                - **🔹 Lang-periode**: Meget lave frekvenser (0.005-0.1 Hz)
                - **🔹 Teleseismisk**: Optimeret til fjerne jordskælv (0.02-2.0 Hz)
                
                ⚠️ **Vigtigt**: Filtre justeres automatisk til din data's sampling rate!
                
                **📊 Data Typer:**
                - **Rådata (Counts)**: Direkte fra instrument, viser elektroniske enheder
                - **Forskydning (mm)**: Kalibreret til fysiske enheder efter response fjernelse
                - **Processeret (mm)**: Forskydning med eventuelt filter og spike fjernelse
                
                **🔬 Analysemuligheder:**
                - **Ms Magnitude**: Beregnes automatisk fra processeret data
                - **FFT Analyse**: Frekvensindhold af overfladebølger  
                - **Før/efter sammenligning**: Se effekt af processering
                - **Ankomsttider**: P, S og overfladebølger markeret på grafer
                
                **💡 Tips:**
                - Start med **🔹 Ingen filtrering** for at se original data
                - Brug **🔹 Bredband** for generel analyse
                - Brug **🔹 Overfladebølger** for præcis Ms beregning
                - Aktivér **sammenligning** for at se processing effekt
                """)
        
        # FORBEDRET filter control panel med klarere labels
        with st.expander("🎛️ Signal Processing Kontrolpanel", expanded=True):
            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            
            with col1:
                # FORBEDRET filter options med klarere beskrivelser og ikoner
                filter_options = {
                    'raw': '🔹 Ingen filtrering (Original data)',
                    'broadband': '🔹 Bredband filter (0.01-25 Hz)',
                    'p_waves': '🔹 P-bølger (1.0-10 Hz)',
                    's_waves': '🔹 S-bølger (0.5-5.0 Hz)', 
                    'surface': '🔹 Overfladebølger (0.02-0.5 Hz) ⭐',
                    'long_period': '🔹 Lang-periode (0.005-0.1 Hz)',
                    'teleseismic': '🔹 Teleseismisk (0.02-2.0 Hz)'
                }
                
                selected_filter = st.selectbox(
                    "🎛️ Vælg Signal Processing",
                    options=list(filter_options.keys()),
                    format_func=lambda x: filter_options[x],
                    index=0,  # Default til ingen filtrering for transparency
                    key="filter_selection",
                    help="⭐ = Anbefalet til Ms magnitude beregning"
                )
            
            with col2:
                remove_spikes = st.checkbox("🔧 Fjern spikes", value=True, key="remove_spikes",
                                        help="Automatisk detektion og fjernelse af instrument spikes")
            
            with col3:
                show_noise_stats = st.checkbox("📊 Støj analyse", value=True, key="show_noise",
                                            help="Beregn SNR og støj statistikker")
            
            with col4:
                # FORBEDRET comparison med automatisk aktivering
                auto_comparison = selected_filter != 'raw'
                show_comparison = st.checkbox("🔄 Før/efter sammenligning", 
                                            value=auto_comparison, key="show_comparison",
                                            help="Sammenlign original data med processeret data")
        
        # FORBEDRET visualization controls med klarere grupering
        with st.expander("📈 Avancerede Visualiseringer", expanded=False):
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                show_snr_plot = st.checkbox("📊 SNR graf", value=False, key="show_snr",
                                        help="Signal-to-Noise Ratio over tid")
            
            with col2:
                show_fft_plot = st.checkbox("🌊 FFT spektrum", value=False, key="show_fft",
                                        help="Frekvens analyse af overfladebølger")
            
            with col3:
                show_p_analysis = st.checkbox("⚡ P-bølge zoom", value=False, key="show_p_analysis",
                                            help="Detaljeret P-ankomst analyse med STA/LTA")
            
            with col4:
                show_raw_data = st.checkbox("📡 Rådata graf", value=False, key="show_raw_data",
                                        help="Vis original instrument counts")
        
        # Component visibility controls med forbedret layout
        st.markdown("**🧭 Komponent Synlighed:**")
        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        
        with col1:
            show_north = st.checkbox("📍 North (N)", value=st.session_state.component_visibility['north'], 
                                key="show_north", help="Nord-syd komponent")
            st.session_state.component_visibility['north'] = show_north
        
        with col2:
            show_east = st.checkbox("📍 East (E)", value=st.session_state.component_visibility['east'], 
                                key="show_east", help="Øst-vest komponent")
            st.session_state.component_visibility['east'] = show_east
        
        with col3:
            show_vertical = st.checkbox("📍 Vertical (Z)", value=st.session_state.component_visibility['vertical'], 
                                    key="show_vertical", help="Op-ned komponent")
            st.session_state.component_visibility['vertical'] = show_vertical
        
        # FORBEDRET Excel export med klarere information
        with col4:
            # Information om hvad der eksporteres
            if selected_filter == 'raw':
                export_info = "📊 Export (Original data)"
                export_help = "Eksporterer originale displacement data uden filtrering"
            else:
                export_info = f"📊 Export ({filter_options[selected_filter].split('(')[0].strip()})"
                export_help = f"Eksporterer data processeret med: {filter_options[selected_filter]}"
            
            if st.button(export_info, use_container_width=True, key="export_excel_btn", help=export_help):
                try:
                    # Brug enhanced processor til export
                    enhanced_processor = self.data_manager.processor
                    
                    # Tilføj arrival times til waveform data
                    waveform_data_with_arrivals = waveform_data.copy()
                    waveform_data_with_arrivals['arrival_times'] = {
                        'P': selected_station.get('p_arrival'),
                        'S': selected_station.get('s_arrival'),
                        'Surface': selected_station.get('surface_arrival')
                    }
                    
                    # Processer med valgte filter indstillinger
                    processed_data = enhanced_processor.process_waveform_with_filtering(
                        waveform_data_with_arrivals, 
                        filter_type=selected_filter,
                        remove_spikes=remove_spikes
                    )
                    
                    if processed_data:
                        # Brug processeret data til Ms beregning
                        filtered_displacement = processed_data['filtered_data']
                        
                        # Beregn Ms magnitude med processeret data
                        ms_magnitude, ms_explanation = enhanced_processor.calculate_ms_magnitude(
                            filtered_displacement['north'], filtered_displacement['east'], 
                            filtered_displacement['vertical'], selected_station['distance_km'], 
                            waveform_data['sampling_rate']
                        )
                        
                        # Opdater waveform_data med processeret data til export
                        export_waveform_data = waveform_data.copy()
                        export_waveform_data['displacement_data'] = filtered_displacement
                        
                        with st.spinner("📊 Genererer Excel fil..."):
                            excel_data = self.data_manager.export_to_excel(
                                selected_eq, selected_station, export_waveform_data, 
                                ms_magnitude, ms_explanation
                            )
                            
                            if excel_data:
                                # FORBEDRET filename med processing information
                                processing_suffix = "" if selected_filter == 'raw' else f"_{selected_filter}"
                                filename = f"seismic_data_{selected_station['network']}_{selected_station['station']}_{selected_eq['time'].strftime('%Y%m%d')}{processing_suffix}.xlsx"
                                
                                st.download_button(
                                    label="⬇️ Download Excel File",
                                    data=excel_data,
                                    file_name=filename,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="download_excel_file"
                                )
                                
                                # FORBEDRET success message med processing info
                                if selected_filter == 'raw':
                                    st.success("✅ Excel fil med original data klar til download!")
                                else:
                                    st.success(f"✅ Excel fil med {filter_options[selected_filter].lower()} processeret data klar!")
                            else:
                                st.error("❌ Kunne ikke generere Excel fil")
                    else:
                        st.error("❌ Fejl ved dataprocessering")
                        
                except Exception as e:
                    st.error(f"❌ Fejl: {str(e)}")
        
        # FORBEDRET main analysis med dynamiske plot navne
        try:
            # Initialisér enhanced processor
            enhanced_processor = self.data_manager.processor
            
            # Forbered data med arrival times til advanced analysis
            waveform_data_with_arrivals = waveform_data.copy()
            waveform_data_with_arrivals['arrival_times'] = {
                'P': selected_station.get('p_arrival'),
                'S': selected_station.get('s_arrival'), 
                'Surface': selected_station.get('surface_arrival')
            }
            
            # Processer data med valgte indstillinger
            processed_data = enhanced_processor.process_waveform_with_filtering(
                waveform_data_with_arrivals,
                filter_type=selected_filter,
                remove_spikes=remove_spikes,
                calculate_noise=show_noise_stats
            )
            
            if not processed_data:
                st.error("❌ Kunne ikke processere data")
                return
            
            # Ekstrahér processerede data komponenter
            times = waveform_data['time']
            sampling_rate = waveform_data['sampling_rate']
            original_data = processed_data['original_data']
            filtered_data = processed_data['filtered_data']
            raw_data = waveform_data['raw_data']
            
            # Beregn Ms magnitude fra processeret data
            ms_magnitude, ms_explanation = enhanced_processor.calculate_ms_magnitude(
                filtered_data['north'], filtered_data['east'], filtered_data['vertical'],
                selected_station['distance_km'], sampling_rate
            )
            
            # FFT analyse på processeret overfladebølger
            surface_arrival = selected_station.get('surface_arrival')
            periods, fft_amplitudes, peak_period, peak_amplitude = None, None, None, None
            
            if surface_arrival:
                # Brug dominerende horizontale komponent til FFT
                max_north = np.max(np.abs(filtered_data['north']))
                max_east = np.max(np.abs(filtered_data['east']))
                dominant_horizontal = filtered_data['north'] if max_north > max_east else filtered_data['east']
                
                periods, fft_amplitudes, peak_period, peak_amplitude = enhanced_processor.calculate_surface_wave_fft(
                    dominant_horizontal, sampling_rate, surface_arrival
                )
            
            # FORBEDRET multi-panel visualization med dynamiske navne
            from plotly.subplots import make_subplots
            
            # Dynamisk bestemmelse af nødvendige plots
            plots_needed = []
            
            if show_raw_data:
                plots_needed.append('raw_signal')
            
            # Altid vis hovedsignal
            plots_needed.append('main_signal')
            
            # Vis Ms beregning hvis relevant
            if ms_magnitude:
                plots_needed.append('ms_calculation')
            
            if show_comparison and selected_filter != 'raw':
                plots_needed.append('comparison')
            if show_snr_plot and 'snr_data' in processed_data and processed_data['snr_data']:
                plots_needed.append('snr')
            if show_fft_plot and periods is not None:
                plots_needed.append('fft')
            
            # Intelligent subplot layout beregning
            num_plots = len(plots_needed)
            if num_plots <= 2:
                rows, cols = 1, 2
            elif num_plots <= 4:
                rows, cols = 2, 2
            elif num_plots <= 6:
                rows, cols = 2, 3
            else:
                rows, cols = 3, 3
            
            # FORBEDRET subplot titles med dynamiske navne
            def get_dynamic_title(plot_type):
                if plot_type == 'raw_signal':
                    return 'Rådata (Counts)'
                elif plot_type == 'main_signal':
                    if selected_filter == 'raw':
                        return 'Signal (mm) - Original displacement'
                    else:
                        filter_name = filter_options[selected_filter].split('(')[0].strip().replace('🔹 ', '')
                        return f'Processeret Signal (mm) - {filter_name}'
                elif plot_type == 'ms_calculation':
                    return 'Ms Magnitude Beregning'
                elif plot_type == 'comparison':
                    return 'Før/Efter Sammenligning'
                elif plot_type == 'snr':
                    return 'Signal-to-Noise Ratio'
                elif plot_type == 'fft':
                    return 'FFT Spektrum - Overfladebølger'
                else:
                    return plot_type
            
            subplot_titles = []
            for plot in plots_needed:
                subplot_titles.append(get_dynamic_title(plot))
            
            # Pad med tomme titler hvis nødvendigt
            while len(subplot_titles) < rows * cols:
                subplot_titles.append('')
            
            # Opret master subplot figure
            fig = make_subplots(
                rows=rows, cols=cols,
                subplot_titles=subplot_titles,
                vertical_spacing=0.08,
                horizontal_spacing=0.10
            )
            
            # Beregn plot positioner
            plot_positions = {}
            for i, plot in enumerate(plots_needed):
                row = (i // cols) + 1
                col = (i % cols) + 1
                plot_positions[plot] = (row, col)
            
            # Forbered arrival times til plotting
            arrivals = [
                (selected_station.get('p_arrival'), 'P', 'red'),
                (selected_station.get('s_arrival'), 'S', 'blue'),
                (selected_station.get('surface_arrival'), 'Surface', 'green')
            ]
            
            # Plot 1: Raw data (hvis valgt)
            if 'raw_signal' in plot_positions:
                row, col = plot_positions['raw_signal']
                if st.session_state.component_visibility['north']:
                    fig.add_trace(go.Scatter(x=times, y=raw_data['north'], mode='lines', 
                                        name='North (raw)', line=dict(color='red', width=1)), row=row, col=col)
                if st.session_state.component_visibility['east']:
                    fig.add_trace(go.Scatter(x=times, y=raw_data['east'], mode='lines', 
                                        name='East (raw)', line=dict(color='green', width=1)), row=row, col=col)
                if st.session_state.component_visibility['vertical']:
                    fig.add_trace(go.Scatter(x=times, y=raw_data['vertical'], mode='lines', 
                                        name='Vertical (raw)', line=dict(color='blue', width=1)), row=row, col=col)
                
                # Tilføj arrival lines til rådata
                for arrival_time, phase, color in arrivals:
                    if arrival_time is not None:
                        fig.add_vline(x=arrival_time, line=dict(color=color, width=2, dash='dash'),
                                    annotation_text=f"{phase}", row=row, col=col)
            
            # Plot 2: FORBEDRET hovedsignal (dynamisk navngivning)
            if 'main_signal' in plot_positions:
                row, col = plot_positions['main_signal']
                
                # Brug korrekte trace navne baseret på processing
                if selected_filter == 'raw':
                    trace_suffix = '(original)'
                else:
                    trace_suffix = '(processeret)'
                
                if st.session_state.component_visibility['north']:
                    fig.add_trace(go.Scatter(x=times, y=filtered_data['north'], mode='lines', 
                                        name=f'North {trace_suffix}', line=dict(color='red', width=1), showlegend=False), row=row, col=col)
                if st.session_state.component_visibility['east']:
                    fig.add_trace(go.Scatter(x=times, y=filtered_data['east'], mode='lines', 
                                        name=f'East {trace_suffix}', line=dict(color='green', width=1), showlegend=False), row=row, col=col)
                if st.session_state.component_visibility['vertical']:
                    fig.add_trace(go.Scatter(x=times, y=filtered_data['vertical'], mode='lines', 
                                        name=f'Vertical {trace_suffix}', line=dict(color='blue', width=1), showlegend=False), row=row, col=col)
                
                # Tilføj arrival lines
                for arrival_time, phase, color in arrivals:
                    if arrival_time is not None:
                        fig.add_vline(x=arrival_time, line=dict(color=color, width=2, dash='dash'),
                                    annotation_text=f"{phase}", row=row, col=col)
            
            # Plot 3: Ms calculation visualization
            if 'ms_calculation' in plot_positions:
                row, col = plot_positions['ms_calculation']
                
                # Bestem og vis dominerende komponent brugt til Ms
                max_north = np.max(np.abs(filtered_data['north']))
                max_east = np.max(np.abs(filtered_data['east']))
                dominant_component = filtered_data['north'] if max_north > max_east else filtered_data['east']
                dominant_name = "North" if max_north > max_east else "East"
                
                fig.add_trace(go.Scatter(x=times, y=dominant_component, mode='lines', 
                                    name=f'{dominant_name} (dominant)', line=dict(color='orange', width=2), showlegend=False), 
                            row=row, col=col)
                
                # Markér maksimum amplitude punkt på dominerende komponent
                max_idx = np.argmax(np.abs(dominant_component))
                max_time = times[max_idx]
                max_amp = dominant_component[max_idx]
                
                fig.add_trace(go.Scatter(x=[max_time], y=[max_amp], mode='markers', 
                                    marker=dict(color='red', size=12, symbol='star'), 
                                    name=f'Max', showlegend=False), 
                            row=row, col=col)
            
            # Plot 4: FORBEDRET comparison
            if 'comparison' in plot_positions:
                row, col = plot_positions['comparison']
                component_for_comparison = 'vertical' if st.session_state.component_visibility['vertical'] else 'north'
                
                fig.add_trace(go.Scatter(x=times, y=original_data[component_for_comparison], mode='lines', 
                                    name='Original', line=dict(color='gray', width=1), showlegend=False), row=row, col=col)
                
                filter_name = filter_options[selected_filter].split('(')[0].strip().replace('🔹 ', '')
                fig.add_trace(go.Scatter(x=times, y=filtered_data[component_for_comparison], mode='lines', 
                                    name=f'Processeret ({filter_name})', line=dict(color='red', width=2), showlegend=False), row=row, col=col)
            
            # Plot 5: SNR (hvis valgt)
            if 'snr' in plot_positions:
                row, col = plot_positions['snr']
                for component, snr_info in processed_data['snr_data'].items():
                    if st.session_state.component_visibility.get(component, False):
                        fig.add_trace(go.Scatter(
                            x=snr_info['times'], y=snr_info['snr_db'], mode='lines',
                            name=f'SNR {component}', line=dict(width=2), showlegend=False
                        ), row=row, col=col)
            
            # Plot 6: FFT (hvis valgt)
            if 'fft' in plot_positions and periods is not None:
                row, col = plot_positions['fft']
                fig.add_trace(go.Scatter(x=periods, y=fft_amplitudes, mode='lines', 
                                    name='FFT', line=dict(color='purple', width=2), showlegend=False), 
                            row=row, col=col)
                
                if peak_period and peak_amplitude:
                    fig.add_trace(go.Scatter(x=[peak_period], y=[peak_amplitude], mode='markers', 
                                        marker=dict(color='red', size=12, symbol='star'), 
                                        name=f'Peak: {peak_period:.1f}s', showlegend=False), 
                                row=row, col=col)
            
            # FORBEDRET layout med processing information
            processing_info = "Original Data" if selected_filter == 'raw' else filter_options[selected_filter].replace('🔹 ', '')
            
            fig.update_layout(
                title=f"Analyse: {selected_station['network']}.{selected_station['station']} - {selected_station['distance_km']:.0f} km - M{selected_eq['magnitude']:.1f} ({processing_info})",
                height=400 + (rows-1) * 300,  # Responsiv højde
                showlegend=True
            )
            
            # Opdater akse labels baseret på plot type
            for plot, (row, col) in plot_positions.items():
                fig.update_xaxes(title_text="Tid (s)", row=row, col=col)
                
                if plot == 'raw_signal':
                    fig.update_yaxes(title_text="Counts", row=row, col=col)
                elif plot in ['main_signal', 'ms_calculation', 'comparison']:
                    fig.update_yaxes(title_text="Forskydning (mm)", row=row, col=col)
                elif plot == 'snr':
                    fig.update_yaxes(title_text="SNR (dB)", row=row, col=col)
                elif plot == 'fft':
                    fig.update_xaxes(title_text="Periode (s)", type="log", row=row, col=col)
                    fig.update_yaxes(title_text="FFT Amplitude", row=row, col=col)
            
            # Render hovedvisualisering
            st.plotly_chart(fig, use_container_width=True)
            
            # P-wave detail analysis (hvis valgt)
            if show_p_analysis:
                st.markdown("### ⚡ P-bølge Detaljeret Analyse")
                
                p_fig, peak_info = enhanced_processor.create_p_wave_zoom_plot(
                    waveform_data, selected_station, processed_data
                )
                
                if p_fig and peak_info:
                    st.plotly_chart(p_fig, use_container_width=True)
                    
                    # P-wave detection summary
                    st.markdown("**P-ankomst Detektion Resultater:**")
                    
                    col1, col2, col3 = st.columns(3)
                    for i, peak in enumerate(peak_info):
                        with [col1, col2, col3][i]:
                            st.metric(
                                f"{peak['component'].capitalize()} Peak",
                                f"{peak['time']:.1f}s",
                                delta=f"{peak['delay']:+.1f}s fra teoretisk"
                            )
                            st.caption(f"STA/LTA: {peak['sta_lta']:.1f}")
                    
                    # Intelligent interpretation
                    best_detection = max(peak_info, key=lambda x: x['sta_lta'])
                    
                    if best_detection['sta_lta'] > 5.0:
                        st.success(f"✅ Klar P-ankomst detekteret på {best_detection['component']} komponent")
                    elif best_detection['sta_lta'] > 3.0:
                        st.warning(f"⚠️ Mulig P-ankomst på {best_detection['component']} komponent")
                    else:
                        st.error("❌ Ingen klar P-ankomst detekteret - muligvis for meget støj")
                        
                else:
                    st.warning("⚠️ Kunne ikke generere P-bølge analyse")
            
            # FORBEDRET metrics dashboard med processing info
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("🎯 Afstand", f"{selected_station['distance_km']:.0f} km")
            with col2:
                p_arrival = selected_station.get('p_arrival')
                st.metric("⚡ P-ankomst", f"{p_arrival:.1f} s" if p_arrival else "N/A")
            with col3:
                s_arrival = selected_station.get('s_arrival')
                st.metric("🌊 S-ankomst", f"{s_arrival:.1f} s" if s_arrival else "N/A")
            with col4:
                if ms_magnitude:
                    st.metric("📊 Ms Magnitude", f"{ms_magnitude}")
                else:
                    st.metric("📊 Ms Magnitude", "N/A")
            with col5:
                if peak_period:
                    st.metric("🎵 Peak Periode", f"{peak_period:.1f} s")
                else:
                    st.metric("🎵 Peak Periode", "N/A")
            
            # Expandable detailed sections
            if ms_magnitude and ms_explanation:
                with st.expander("🧮 Ms Magnitude Beregning"):
                    st.markdown(ms_explanation)
            
            if peak_period and peak_amplitude:
                with st.expander("🌊 Overfladebølge Analyse"):
                    st.info(f"**Peak periode:** {peak_period:.1f} sekunder (optimal ~20s)")
                    st.info(f"**Peak amplitude:** {peak_amplitude:.2e} (FFT magnitude)")
                    
                    if abs(peak_period - 20.0) < 5.0:
                        st.success("✅ Peak periode tæt på optimal 20s for Ms beregning")
                    else:
                        st.warning("⚠️ Peak periode afviger fra optimal 20s")
            
            # FORBEDRET data quality summary med processing info
            available_components = waveform_data.get('available_components', [])
            processing_summary = "Original displacement data" if selected_filter == 'raw' else f"Data processeret med {filter_options[selected_filter].lower()}"
            
            st.caption(f"✅ IRIS data: {', '.join(available_components)} komponenter fra {selected_station['network']}.{selected_station['station']} - {processing_summary}")
            
            # TILFØJET: Processing quality feedback
            if selected_filter != 'raw' and processed_data.get('spike_info'):
                spike_summary = []
                for component, spike_info in processed_data['spike_info'].items():
                    if spike_info.get('num_spikes', 0) > 0:
                        spike_summary.append(f"{component}: {spike_info['num_spikes']} spikes fjernet")
                
                if spike_summary:
                    st.caption(f"🔧 Signal processing: {', '.join(spike_summary)}")
            
        except Exception as e:
            st.error(f"❌ Analyse fejl: {str(e)}")
            import traceback
            st.error(traceback.format_exc())
    
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

