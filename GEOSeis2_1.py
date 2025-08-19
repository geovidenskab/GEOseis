"""
GEOseis v2.1 - Streamlined Seismic Analysis Platform
=====================================================
Version 2.1 - Med forbedrede bølgehastigheder og teori-sektion
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import traceback
import warnings
import time
from obspy import UTCDateTime
from io import BytesIO
import xlsxwriter
from waveform_visualizer import WaveformVisualizer
import folium.plugins
from scipy.fft import fft, fftfreq

# ==========================================
# TILFØJ: Import af egne moduler
# ==========================================
from toast_manager import ToastManager
from seismic_processor import EnhancedSeismicProcessor
from data_manager import StreamlinedDataManager
#from triangulation import render_triangulation_view
# ==========================================
# TILFØJ: Check ObsPy availability
# ==========================================
try:
    import obspy
    OBSPY_AVAILABLE = True
except ImportError:
    OBSPY_AVAILABLE = False
    st.error("❌ ObsPy er påkrævet for fuld funktionalitet. Installer med: pip install obspy")

# Import tekster direkte
from texts import texts, help_texts

# Konfiguration
st.set_page_config(
    page_title="GEOSeis 2.1",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Handle sprog parameter
def handle_language_change():
    """Handle language change from URL parameters"""
    params = st.query_params
    if 'lang' in params:
        lang = params['lang']
        if lang in ['da', 'en']:
            st.session_state.language = lang
            st.query_params.clear()

# Kald sprog handler
handle_language_change()

# Initialize sprog
if 'language' not in st.session_state:
    st.session_state.language = 'da'
    
def get_cached_taup_model():
    """Returnerer cached TauPyModel instans"""
    if 'taup_model' not in st.session_state:
        from obspy.taup import TauPyModel
        st.session_state.taup_model = TauPyModel(model="iasp91")
        print("TauPyModel created and cached")
    return st.session_state.taup_model

def get_cached_data_manager():
    """Returnerer cached DataManager instans"""
    if 'data_manager' not in st.session_state:
        st.session_state.data_manager = StreamlinedDataManager()
        print("StreamlinedDataManager created and cached")
    return st.session_state.data_manager

def get_cached_seismic_processor():
    """Returnerer cached SeismicProcessor instans"""
    if 'seismic_processor' not in st.session_state:
        st.session_state.seismic_processor = EnhancedSeismicProcessor()
        print("EnhancedSeismicProcessor created and cached")
    return st.session_state.seismic_processor

def ensure_utc_datetime(time_obj):
    """
    Simpel tid konvertering til UTCDateTime for Streamlit Cloud kompatibilitet.
    """
    if time_obj is None:
        return None
    
    if isinstance(time_obj, UTCDateTime):
        return time_obj
    
    try:
        # Prøv direkte konvertering først
        return UTCDateTime(time_obj)
    except:
        # Hvis det fejler, prøv via string
        try:
            return UTCDateTime(str(time_obj))
        except:
            raise ValueError(f"Kunne ikke konvertere tid: {time_obj}")

def format_earthquake_time(time_value, format_string='%d %b %Y'):
    """
    Formaterer earthquake tid fra enhver kilde.
    Håndterer ISO strings, datetime objekter, og UTCDateTime.
    
    Args:
        time_value: Tid som string, datetime, eller UTCDateTime
        format_string: strftime format string (default: '%d %b %Y')
        
    Returns:
        str: Formateret tidsstring eller fallback
    """
    if time_value is None:
        return "Unknown"
    
    # Hvis det allerede er en string, prøv at parse den
    if isinstance(time_value, str):
        try:
            # Parse ISO format
            if 'T' in time_value:
                # Håndter både med og uden Z
                time_value = time_value.replace('Z', '+00:00')
                dt = datetime.fromisoformat(time_value)
            else:
                # Prøv andre formater
                dt = datetime.strptime(time_value, '%Y-%m-%d %H:%M:%S')
            return dt.strftime(format_string)
        except:
            # Hvis parsing fejler, returner bare de første 10 karakterer (dato)
            return time_value[:10] if len(time_value) >= 10 else time_value
    
    # Check for datetime-lignende objekter
    elif hasattr(time_value, 'strftime'):
        try:
            return time_value.strftime(format_string)
        except:
            return str(time_value)[:10]
    
    # Check for ObsPy UTCDateTime
    elif hasattr(time_value, 'datetime'):
        try:
            return time_value.datetime.strftime(format_string)
        except:
            return str(time_value)[:10]
    
    # Sidste forsøg - prøv at konvertere til datetime
    else:
        try:
            dt = datetime.fromtimestamp(float(time_value))
            return dt.strftime(format_string)
        except:
            return str(time_value)[:10] if len(str(time_value)) >= 10 else str(time_value)

def safe_get_earthquake_field(earthquake, field, default='Unknown'):
    """
    Sikkert henter felt fra earthquake dictionary eller objekt.
    
    Args:
        earthquake: Dictionary eller objekt med earthquake data
        field: Felt navn at hente
        default: Default værdi hvis felt ikke findes
        
    Returns:
        Feltværdi eller default
    """
    if earthquake is None:
        return default
    
    if isinstance(earthquake, dict):
        return earthquake.get(field, default)
    else:
        return getattr(earthquake, field, default)



class GEOSeisV2:
    """Main application class for GEOSeis 2.1"""
    
    def __init__(self):
        self.setup_session_state()
        self.load_modern_css()
        
        # ==========================================
        # CACHED MANAGERS - Initialiseres kun én gang!
        # ==========================================
        
        # Toast Manager (lightweight - behøver ikke caching)
        self.toast_manager = ToastManager()
        
        # Data Manager - CACHED
        if OBSPY_AVAILABLE:
            if 'data_manager' not in st.session_state:
                from data_manager import StreamlinedDataManager
                st.session_state.data_manager = StreamlinedDataManager()
                print("StreamlinedDataManager created ONCE in session state")
            self.data_manager = st.session_state.data_manager
        else:
            self.data_manager = None
        
        # Seismic Processor - CACHED
        if OBSPY_AVAILABLE:
            if 'seismic_processor' not in st.session_state:
                from seismic_processor import EnhancedSeismicProcessor
                st.session_state.seismic_processor = EnhancedSeismicProcessor()
                print("EnhancedSeismicProcessor created ONCE in session state")
            self.processor = st.session_state.seismic_processor
        else:
            self.processor = None
        
        # Waveform Visualizer (lightweight - behøver ikke caching)
        self.visualizer = WaveformVisualizer()
        
        # Check IRIS forbindelse
        if self.data_manager and not self.data_manager.client:
            st.warning("⚠️ Kunne ikke oprette forbindelse til IRIS. Nogle funktioner er begrænsede.")
            
        # TILFØJ DETTE til slutningen af __init__:
        if 'session_initialized' not in st.session_state:
            st.session_state.session_initialized = True
            st.session_state.last_station_key = None
            print("🎯 Session tracking initialized")

   
    def load_modern_css(self):
            """Load modern CSS styling - uden emojis og afdæmpet"""
            st.markdown("""
            <style>
            /* Reset og base styling */
            * {
                box-sizing: border-box;
            }
            
            /* Kompakt breadcrumb-titel kombination */
            .stMarkdown h2 {
                margin-top: 0 !important;
            }

            /* Reducer spacing efter breadcrumb-titel */
            div[style*="margin-bottom: 1rem"] + * {
                margin-top: 0 !important;
            }
            
            
            /* Kompakt header */
            .stApp > header {
                height: 0rem !important;
            }
            
            .block-container {
                padding-top: 0rem !important;
                padding-bottom: 2rem !important;
                max-width: 100%;
            }
            
            /* Header design */
            .main-header {
                background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 50%, #D6EBFD 100%);
                padding: 0.75rem 2rem;
                margin: -1rem -3rem 1.5rem -3rem;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                border-bottom: 1px solid #E9ECEF;
                position: relative;
                z-index: 100;
            }
            
            /* Header content */
            .header-content {
                display: flex;
                align-items: center;
                justify-content: space-between;
                max-width: 1400px;
                margin: 0 auto;
            }
            
            /* Title section */
            .title-section {
                display: flex;
                align-items: center;
                gap: 1rem;
            }
            
            /* Title text */
            .title-text {
                display: flex;
                flex-direction: column;
                gap: 0.1rem;
            }
            /* Earth emoji - mindre størrelse */
            .earth-emoji {
                font-size: 3.75rem;  /* Reduceret fra 2.5rem */
                line-height: 1;
            }
            
        
            
            /* Main title */
            .main-title {
                color: #2C3E50 !important;
                font-size: 1.75rem !important;
                font-weight: 700 !important;
                margin: 0 !important;
                padding: 0 !important;
                line-height: 1.1 !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', sans-serif;
            }
            
            /* Subtitle */
            .main-subtitle {
                color: #495057 !important;
                font-size: 0.9rem !important;
                margin: 0 !important;
                padding: 0 !important;
                font-weight: 400 !important;
            }
            
            /* Language flags */
            .language-flags {
                display: flex;
                gap: 0.75rem;
                align-items: center;
            }
            
            .language-flags a {
                display: inline-block;
                padding: 4px;
                cursor: pointer;
                font-size: 1.3rem;
                opacity: 0.6;
                transition: all 0.2s ease;
                border-radius: 4px;
                text-decoration: none;
            }
            
            .language-flags a:hover {
                opacity: 1;
                transform: scale(1.15);
            }
            
            .lang-button.active {
                opacity: 1 !important;
                transform: scale(1.1);
                background-color: rgba(93, 173, 226, 0.1);
                border-radius: 4px;
            }
            
            /* Main container */
            .main {
                padding: 0;
                max-width: 1400px;
                margin: 0 auto;
            }
            
            /* Typography */
            .stApp {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', sans-serif;
            }
            
            /* Headers */
            h1, h2, h3, h4, h5, h6,
            .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
                color: #2C3E50 !important;
                font-weight: 600 !important;
                line-height: 1.3 !important;
                margin-top: 1rem !important;
                margin-bottom: 0.5rem !important;
            }
            
            h1, .stMarkdown h1 { font-size: 2rem !important; }
            h2, .stMarkdown h2 { font-size: 1.5rem !important; }
            h3, .stMarkdown h3 { font-size: 1.25rem !important; }
            
            /* Paragraphs */
            p, .stMarkdown p {
                color: #34495E !important;
                font-size: 1rem !important;
                line-height: 1.6 !important;
                margin-bottom: 0.5rem !important;
            }
            
            /* Buttons */
            .stButton > button {
                background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
                color: #495057 !important;
                border: 1px solid #E9ECEF !important;
                padding: 0.6rem 1.5rem !important;
                font-size: 1rem !important;
                font-weight: 500 !important;
                border-radius: 8px !important;
                transition: all 0.2s ease !important;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
                text-align: center !important;
                min-height: 42px !important;
            }
            
            .stButton > button:hover {
                background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
                border-color: #B8DAFF !important;
                transform: translateY(-1px) !important;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1) !important;
            }
            
            /* Primary buttons */
            .stButton > button[kind="primary"],
            [data-testid="column"] .stButton > button[kind="primary"] {
                background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
                color: #0056B3 !important;
                border: 1.5px solid #5DADE2 !important;
                font-weight: 600 !important;
                box-shadow: 0 0 0 2px rgba(93, 173, 226, 0.1) !important;
            }
            
            /* Info boxes */
            .stInfo {
                background-color: #E8F4FD !important;
                border-left: 4px solid #5DADE2 !important;
                padding: 1rem !important;
                border-radius: 8px !important;
                font-size: 1rem !important;
            }
            
            .stWarning {
                background-color: #FFF3CD !important;
                border-left: 4px solid #FFC107 !important;
                padding: 1rem !important;
                border-radius: 8px !important;
            }
            
            /* Sidebar styling */
            section[data-testid="stSidebar"] {
                background: #F8F9FA;
                border-right: 1px solid #E9ECEF;
            }
            
            /* Sidebar button styling */
            section[data-testid="stSidebar"] .stButton > button {
                text-align: left !important;
                justify-content: flex-start !important;
                background: transparent !important;
                border: 1px solid #E9ECEF !important;
                border-radius: 0.375rem !important;
                padding: 0.5rem 1rem !important;
                margin-bottom: 0.25rem !important;
                transition: all 0.15s ease !important;
                font-weight: 500 !important;
                color: #495057 !important;
                width: 100% !important;
            }
            
            /* Sidebar button hover */
            section[data-testid="stSidebar"] .stButton > button:hover {
                background: #E8F4FD !important;
                border-color: #0066CC !important;
                color: #0066CC !important;
            }
            
            /* Active sidebar button */
            section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
                background: linear-gradient(to right, #E8F4FD 0%, #F8F9FA 100%) !important;
                border-left: 3px solid #0066CC !important;
                font-weight: 600 !important;
                color: #0066CC !important;
            }
            
            
            .stSuccess {
                background-color: #D4EDDA !important;
                border-left: 4px solid #28A745 !important;
                padding: 1rem !important;
                border-radius: 8px !important;
            }
            
            .stError {
                background-color: #F8D7DA !important;
                border-left: 4px solid #DC3545 !important;
                padding: 1rem !important;
                border-radius: 8px !important;
            }
            
            /* Sidebar */
            section[data-testid="stSidebar"] {
                background: #F8F9FA;
                padding-top: 2rem;
                width: 260px !important;
            }
            
            section[data-testid="stSidebar"] .stButton > button {
                background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
                color: #495057 !important;
                border: 1px solid #E9ECEF !important;
                font-size: 0.95rem !important;
                padding: 0.5rem 1rem !important;
                width: 100%;
                text-align: left !important;
            }
            /* ========== CUSTOM TABS STYLING ========== */
    
            /* Tab container - matcher GEOSeis styling */
            .stTabs [data-baseweb="tab-list"] {
                gap: 0rem;
                background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 50%, #D6EBFD 100%);
                padding: 0.15rem;
                border-radius: 0.375rem;
                border: 1px solid #E9ECEF;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                margin-bottom: 0.rem;
            }
            
            /* Individual tab styling */
            .stTabs [data-baseweb="tab"] {
                height: 1.rem;
                padding: 0 1rem;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 0.375rem;
                margin: 0.125rem;
                transition: all 0.2s ease;
                font-weight: 500;
                color: #495057;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                position: relative;
            }
            
            /* Tab hover effect */
            .stTabs [data-baseweb="tab"]:hover {
                background: rgba(255, 255, 255, 0.7);
                border-color: #0066CC;
                color: #0066CC;
                transform: translateY(-1px);
                box-shadow: 0 2px 8px rgba(0,102,204,0.15);
            }
            
            /* Active tab styling - matcher GEOSeis blue theme */
            .stTabs [data-baseweb="tab"][aria-selected="true"] {
                background: linear-gradient(135deg, #0066CC 0%, #4A90E2 100%);
                border-color: #0066CC;
                color: white;
                font-weight: 600;
                box-shadow: 0 4px 12px rgba(0,102,204,0.25);
                transform: translateY(-2px);
            }
            
            /* Active tab text styling */
            .stTabs [data-baseweb="tab"][aria-selected="true"] > div {
                color: white !important;
                text-shadow: 0 1px 2px rgba(0,0,0,0.1);
            }
            
            /* Tab content styling */
            .stTabs [data-baseweb="tab-panel"] {
                padding: 1.0 rem 0 0 0;
                background: white;
                border-radius: 0.5rem;
                border: 1px solid #E9ECEF;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                margin-top: -0.5rem;
                position: relative;
                z-index: 1;
            }
            
            /* Tab content inner padding */
            .stTabs [data-baseweb="tab-panel"] > div {
                padding: 0.75rem 0.75rem;
            }
            
            /* Remove default tab indicators */
            .stTabs [data-baseweb="tab-highlight"] {
                display: none;
            }
            
            .stTabs [data-baseweb="tab-border"] {
                display: none;
            }
            
            /* Special styling for analysis tabs with icons */
            .stTabs [data-baseweb="tab"] div[data-testid="stMarkdownContainer"] p {
                margin: 0;
                font-size: 1.4rem;
                font-weight: inherit;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            /* Icon styling within tabs */
            .stTabs [data-baseweb="tab"] div[data-testid="stMarkdownContainer"] p::before {
                content: attr(data-icon);
                font-size: 1.4rem;
                opacity: 0.9;
            }
            
            /* Responsive tabs for smaller screens */
            @media (max-width: 768px) {
                .stTabs [data-baseweb="tab-list"] {
                    flex-wrap: wrap;
                    gap: 0.25rem;
                }
                
                .stTabs [data-baseweb="tab"] {
                    min-width: calc(50% - 0.25rem);
                    padding: 0 1rem;
                    font-size: 0.9rem;
                }
            }
            
            /* Status panel styling */
            .status-text {
                font-size: 0.85rem;
                line-height: 1.2;
                color: #6c757d;
            }
            
            
            /* Remove Streamlit branding */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            
            
            /* ==============================================
            FOLIUM FULLSCREEN Z-INDEX FIX
            ============================================== */

            /* Folium fullscreen container fix */
            .leaflet-control-fullscreen-button {
                z-index: 1000 !important;
            }

            /* Når kortet er i fullscreen mode */
            .leaflet-fullscreen-on .leaflet-container {
                z-index: 999999 !important;
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                width: 100vw !important;
                height: 100vh !important;
            }

            /* Skjul Streamlit elementer når fullscreen er aktiv */
            .leaflet-fullscreen-on .main-header {
                z-index: 1 !important;
                opacity: 0 !important;
                visibility: hidden !important;
            }

            .leaflet-fullscreen-on section[data-testid="stSidebar"] {
                z-index: 1 !important;
                opacity: 0 !important;
                visibility: hidden !important;
            }

            .leaflet-fullscreen-on .block-container {
                z-index: 1 !important;
            }

            /* Sikre at alle Leaflet kontrols er ovenpå */
            .leaflet-fullscreen-on .leaflet-control-container {
                z-index: 1000000 !important;
            }

            .leaflet-fullscreen-on .leaflet-control {
                z-index: 1000001 !important;
            }

            /* Fix for Leaflet controls i normal mode */
            .leaflet-control-container {
                z-index: 1000 !important;
            }

            .leaflet-control {
                z-index: 1001 !important;
            }

            /* Alternatativ løsning: Overrider Streamlit's z-index hierarki */
            .stApp {
                z-index: auto !important;
            }

            /* Sikre at map container kan gå til fullscreen */
            iframe[title*="st_folium"] {
                z-index: 1 !important;
            }

            /* Når fullscreen er aktiv, skjul alt andet */
            body.leaflet-fullscreen-on > *:not(.leaflet-container):not(.leaflet-control-container) {
                z-index: 1 !important;
                opacity: 0 !important;
            }

            /* Specifik fix for streamlit-folium komponenten */
            .leaflet-fullscreen-on {
                background: #000 !important;
            }

            /* Ensure fullscreen exit button is visible */
            .leaflet-fullscreen-on .leaflet-control-fullscreen a {
                z-index: 1000002 !important;
                color: white !important;
                background: rgba(0,0,0,0.7) !important;
                border-radius: 4px !important;
            }
            
            /* Fjern Streamlit header og toolbar */
                header[data-testid="stHeader"] {
                    display: none !important;
                }

                .stAppToolbar {
                    display: none !important;
                }

                .main .block-container {
                    padding-top: 1rem !important;
                }

                [data-testid="stToolbar"] {
                    display: none !important;
                }

                #MainMenu {visibility: hidden;}
                footer {visibility: hidden;}
            </style>
            """, unsafe_allow_html=True)


    def setup_session_state(self):
        """Initialize all session state variables"""
        # Navigation
        if 'current_view' not in st.session_state:
            st.session_state.current_view = 'start'
        
        # Language
        if 'language' not in st.session_state:
            st.session_state.language = 'da'
        
        # Data state
        if 'latest_earthquakes' not in st.session_state:
            st.session_state.latest_earthquakes = None
        
        if 'search_results' not in st.session_state:
            st.session_state.search_results = None
        
        # Selection state
        if 'selected_earthquake' not in st.session_state:
            st.session_state.selected_earthquake = None
        
        if 'selected_station' not in st.session_state:
            st.session_state.selected_station = None
        
        if 'station_list' not in st.session_state:
            st.session_state.station_list = None
        
        if 'waveform_data' not in st.session_state:
            st.session_state.waveform_data = None
        
        # Search parameters
        if 'magnitude_range' not in st.session_state:
            st.session_state.magnitude_range = (6.5, 8.0)
        
        if 'year_range' not in st.session_state:
            current_year = datetime.now().year
            st.session_state.year_range = (2023, current_year)
        
        if 'depth_range' not in st.session_state:
            st.session_state.depth_range = (1, 200)
        
        if 'max_earthquakes' not in st.session_state:
            st.session_state.max_earthquakes = 10
        
        # Station search parameters
        if 'target_stations' not in st.session_state:
            st.session_state.target_stations = 3
        
        if 'station_search_radius' not in st.session_state:
            st.session_state.station_search_radius = 2000
            
            
    def render_header(self):
        """Renderer kompakt header med sprog toggle"""
        st.markdown(f'''
        <div class="main-header">
            <div class="header-content">
                <div class="title-section">
                    <span class="earth-emoji">🌍</span>
                    <div class="title-text">
                        <h1 class="main-title">{texts[st.session_state.language]["app_title"]}</h1>
                        <p class="main-subtitle">{texts[st.session_state.language]["app_subtitle"]}</p>
                    </div>
                </div>
                <div class="language-flags">
                    <a href="?lang=da" title="Dansk">
                        <span class="lang-button {"active" if st.session_state.language == "da" else ""}">🇩🇰</span>
                    </a>
                    <a href="?lang=en" title="English">
                        <span class="lang-button {"active" if st.session_state.language == "en" else ""}">🇬🇧</span>
                    </a>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)

    def render_sidebar(self):
        """Render the sidebar navigation med hierarkisk struktur og auto-kollaps"""
        with st.sidebar:
            
            st.markdown("""
            <style>
            /* Venstrestil al tekst i sidebar buttons */
            section[data-testid="stSidebar"] .stButton > button {
                text-align: left !important;
                justify-content: flex-start !important;
            }
            
            /* Active state styling */
            section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
                background: linear-gradient(to right, #E8F4FD 0%, #F8F9FA 100%) !important;
                border-left: 3px solid #0066CC !important;
                font-weight: 600 !important;
            }
            
            /* Status panel styling */
            .status-text {
                font-size: 0.85rem;
                line-height: 1.3;
                color: #6c757d;
            }
            .status-header {
                font-size: 0.9rem;
                font-weight: 600;
                color: #495057;
                margin-bottom: 2px;
            }
            </style>
            """, unsafe_allow_html=True)
            
            st.markdown("## 🌍 GEOSeis 2.1")

            # Startside
            if st.button("Startside", use_container_width=True,
                        type="primary" if st.session_state.current_view == 'start' else "secondary"):
                st.session_state.current_view = 'start'
            
            # Søg data sektion
            data_views = ['data_search', 'analysis_stations']
            data_expanded = st.session_state.current_view in data_views
            
            with st.expander("Søg data", expanded=data_expanded):
                if st.button("Jordskælv", use_container_width=True,
                            type="primary" if st.session_state.current_view == 'data_search' else "secondary"):
                    st.session_state.current_view = 'data_search'
                
                disabled = not st.session_state.get('selected_earthquake')
                if st.button("Målestationer", use_container_width=True,
                            type="primary" if st.session_state.current_view == 'analysis_stations' else "secondary",
                            disabled=disabled):
                    st.session_state.current_view = 'analysis_stations'
            
            # FORENKLET Analyse sektion - kun én knap!
            has_station = st.session_state.get('selected_station') is not None
            
            if st.button("Seismisk Analyse", use_container_width=True,
                        type="primary" if st.session_state.current_view == 'unified_analysis' else "secondary",
                        disabled=not has_station):
                st.session_state.current_view = 'unified_analysis'
            
            # Data eksport
            has_waveform = st.session_state.get('waveform_data') is not None
            if st.button("Data eksport", use_container_width=True,
                        type="primary" if st.session_state.current_view == 'tools_export' else "secondary",
                        disabled=not has_waveform):
                st.session_state.current_view = 'tools_export'
                
            st.link_button("Åbn GEOepicenter", 'https://geovidenskab.github.io/epicenter/', use_container_width=True)
                    
            
            # Hjælp sektion
            help_views = ['theory_guide', 'about']
            help_expanded = st.session_state.current_view in help_views
            
            with st.expander("Hjælp og viden", expanded=help_expanded):
                if st.button("Teori og metoder", use_container_width=True,
                            type="primary" if st.session_state.current_view == 'theory_guide' else "secondary"):
                    st.session_state.current_view = 'theory_guide'
                
                if st.button("Om GEOSeis 2.1", use_container_width=True,
                            type="primary" if st.session_state.current_view == 'about' else "secondary"):
                    st.session_state.current_view = 'about'
            
            # Status panel
            st.markdown("### Status")
            
            if st.session_state.get('selected_earthquake'):
                eq = st.session_state.selected_earthquake
                st.markdown(
                    f"""<div class="status-text">
                    <div class="status-header">Jordskælv:</div>
                    M{eq.get('magnitude', 0):.1f} • {eq.get('depth', 0):.0f} km dybde<br>
                    {format_earthquake_time(eq.get('time'), '%d/%m/%Y')}
                    </div>""", 
                    unsafe_allow_html=True
                )
            else:
                st.markdown('<div class="status-text">Intet jordskælv valgt</div>', unsafe_allow_html=True)
            
            st.markdown("")
            
            if st.session_state.get('selected_station'):
                station = st.session_state.selected_station
                st.markdown(
                    f"""<div class="status-text">
                    <div class="status-header">Station:</div>
                    {station['network']}.{station['station']}<br>
                    {station['distance_km']:.0f} km afstand
                    </div>""", 
                    unsafe_allow_html=True
                )
            else:
                st.markdown('<div class="status-text">Ingen station valgt</div>', unsafe_allow_html=True)
            
            st.markdown("")
            
            if st.session_state.get('waveform_data'):
                if st.session_state.get('ms_result'):
                    ms_value = st.session_state.ms_result
                    st.markdown(
                        f"""<div class="status-text">
                        <div class="status-header">Data status:</div>
                        ✓ Data hentet<br>
                        ✓ Ms = {ms_value:.1f}
                        </div>""", 
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown(
                        """<div class="status-text">
                        <div class="status-header">Data status:</div>
                        ✓ Data hentet
                        </div>""", 
                        unsafe_allow_html=True
                    )
            else:
                st.markdown('<div class="status-text">Ingen data hentet</div>', unsafe_allow_html=True)


    
    def render_breadcrumb_with_title(self, title):
        """Kombineret breadcrumb og titel for minimal vertikal plads"""
        
        if st.session_state.current_view == 'start':
            st.markdown(f"## {title}")
            return
        
        # Byg breadcrumb elementer
        elements = []
        
        # Hjem
        elements.append(f'<a href="#" onclick="return false;" style="color: #6c757d; text-decoration: none; font-size: 0.8rem;">Hjem</a>')
        
        # Jordskælv
        if st.session_state.get('selected_earthquake'):
            eq = st.session_state.selected_earthquake
            if eq:
                formatted_date = format_earthquake_time(eq.get('time'), '%d/%m/%Y')
                elements.append(f'<span style="color: #6c757d; font-size: 0.8rem;"> -> Earthquake: M{eq["magnitude"]:.1f}, Date: {formatted_date}, Depth: {eq["depth"]:.0f} km</span>')
                    
        # Station
        if st.session_state.get('selected_station'):
            station = st.session_state.selected_station
            elements.append(f'<span style="color: #6c757d; font-size: 0.8rem;"> -> Station: {station["network"]}.{station["station"]}, Distance: {station["distance_km"]:.0f} km </span>')
        
        # Breadcrumb HTML
        breadcrumb_html = ' <span style="color: #dee2e6; font-size: 0.7rem;">›</span> '.join(elements)
        
        # Kombiner breadcrumb og titel i én HTML blok
        col1, col2 = st.columns([10, 1])
        
        with col1:
            st.markdown(
                f"""<div style="margin-bottom: 1rem;">
                <div style="font-size: 0.8rem; color: #6c757d; margin-bottom: 0.2rem;">
                {breadcrumb_html}
                </div>
                <h2 style="margin: 0; padding: 0; color: #2C3E50; font-size: 2rem; font-weight: 600;">{title}</h2>
                </div>""",
                unsafe_allow_html=True
            )
        
        with col2:
            # Tilbage knap
            if st.button("← Tilbage", key=f"back_{st.session_state.current_view}", 
                        help="Tilbage", use_container_width=True):
                # Logik for tilbage navigation
                if st.session_state.current_view == 'unified_analysis':
                    st.session_state.current_view = 'analysis_stations'
                elif st.session_state.current_view == 'analysis_magnitude':
                    st.session_state.current_view = 'unified_analysis'
                elif st.session_state.current_view == 'analysis_ms_advanced':
                    st.session_state.current_view = 'analysis_magnitude'
                elif st.session_state.current_view == 'analysis_stations':
                    st.session_state.current_view = 'data_search'
                elif st.session_state.current_view == 'tools_export':
                    st.session_state.current_view = 'unified_analysis'
                elif st.session_state.current_view == 'analysis_wave':
                    st.session_state.current_view = 'unified_analysis'
                else:
                    st.session_state.current_view = 'start'
                st.rerun()
    
    def render_earthquake_results(self, earthquakes):
        """Display earthquake search results"""
        if not earthquakes:
            st.warning("Ingen jordskælv fundet med de valgte kriterier")
            return
        
        #st.success(f"Fandt {len(earthquakes)} jordskælv")
        
        # Vis resultater som klikbare rækker
        for idx, eq in enumerate(earthquakes[:10]):  # Vis max 10
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
            
            with col1:
                if st.button(
                    f"M{eq['magnitude']:.1f} - {eq.get('location', 'Unknown')[:30]}",
                    key=f"eq_select_{idx}",
                    use_container_width=True
                ):
                    # Gem valgt jordskælv og skift til stationsvalg (ikke seismogram)
                    st.session_state.selected_earthquake = eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET
                    # Reset station data
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    
                    # Vis toast
                    self.toast_manager.show(
                        f"Valgt: M{eq['magnitude']:.1f} jordskælv",
                        toast_type='success',
                        duration=2.0
                    )
                    st.rerun()
            
            with col2:
                st.text(format_earthquake_time(eq['time'], '%d-%m-%Y'))
            
            with col3:
                st.text(f"{eq.get('depth', 0):.0f} km")
            
            with col4:
                st.text(f"{eq.get('latitude', 0):.1f}°")
            
            with col5:
                st.text(f"{eq.get('longitude', 0):.1f}°")
        
        # Vis også på kort
        st.markdown("### 🗺️ Kort visning")
        eq_df = pd.DataFrame(earthquakes)
        earthquake_map = self.create_optimized_map(eq_df)
        
        if earthquake_map:
            map_data = st_folium(
                earthquake_map,
                width=950,
                height=500,
                returned_objects=["last_object_clicked", "last_clicked"],
                key="search_results_map"
            )
            
            # Process klik på kortet
            if map_data and (map_data.get("last_clicked") or map_data.get("last_object_clicked")):
                clicked_eq = self.process_earthquake_click(map_data, eq_df)
                
                if clicked_eq:
                    st.session_state.selected_earthquake = clicked_eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.rerun()

    def render_data_search_view(self):
        """Render the earthquake search view"""
        st.markdown(f"## {texts[st.session_state.language]['nav_earthquake_search']}")
        
        # Variabler til at holde form værdier
        mag_range = None
        year_range = None
        depth_range = None
        max_results = None
        
        # Search form
        with st.form("earthquake_search"):
            st.markdown(f"### {texts[st.session_state.language]['search_criteria']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                mag_range = st.slider(
                    texts[st.session_state.language]['magnitude_range'],
                    min_value=4.0,
                    max_value=9.0,
                    value=st.session_state.magnitude_range,
                    step=0.1,
                    help=texts[st.session_state.language]['magnitude_help']
                )
                
                year_range = st.slider(
                    texts[st.session_state.language]['date_range'],
                    min_value=1990,
                    max_value=datetime.now().year,
                    value=st.session_state.year_range,
                    help=texts[st.session_state.language]['date_help']
                )
            
            with col2:
                depth_range = st.slider(
                    texts[st.session_state.language]['depth_range'],
                    min_value=0,
                    max_value=700,
                    value=st.session_state.depth_range,
                    step=10,
                    help=texts[st.session_state.language]['depth_help']
                )
                
                max_results = st.number_input(
                    texts[st.session_state.language]['max_results'],
                    min_value=1,
                    max_value=500,
                    value=25
                )
            
            submitted = st.form_submit_button(
                texts[st.session_state.language]['search_button'],
                type="primary"
            )
            
            # Gem form værdier i session state når submitted
            if submitted:
                st.session_state.form_submitted = True
                st.session_state.form_mag_range = mag_range
                st.session_state.form_year_range = year_range
                st.session_state.form_depth_range = depth_range
                st.session_state.form_max_results = max_results
        
        # UDEN FOR form - check om form blev submitted
        if st.session_state.get('form_submitted', False) and self.data_manager:
            # Hent værdier fra session state
            mag_range = st.session_state.get('form_mag_range', st.session_state.magnitude_range)
            year_range = st.session_state.get('form_year_range', st.session_state.year_range)
            depth_range = st.session_state.get('form_depth_range', st.session_state.depth_range)
            max_results = st.session_state.get('form_max_results', 25)
            
            # Opdater permanente session state værdier
            st.session_state.magnitude_range = mag_range
            st.session_state.year_range = year_range
            st.session_state.depth_range = depth_range
            
            # Reset submitted flag
            st.session_state.form_submitted = False
            
            with st.spinner(texts[st.session_state.language]['loading']):
                earthquakes = self.data_manager.fetch_latest_earthquakes(
                    magnitude_range=mag_range,
                    year_range=year_range,
                    depth_range=depth_range,
                    limit=max_results
                )
                
                if earthquakes:
                    st.session_state.search_results = earthquakes
                    st.success(f"✅ Fandt {len(earthquakes)} jordskælv")
                    
                    # Vis toast notification
                    self.toast_manager.show(
                        f"Fandt {len(earthquakes)} jordskælv",
                        toast_type='success',
                        duration=3.0
                    )
                else:
                    st.warning("Ingen jordskælv fundet med de valgte kriterier")
        
        # Vis resultater UDEN FOR form
        if st.session_state.get('search_results'):
            self.render_earthquake_results(st.session_state.search_results)

    def render_earthquake_map(self, earthquakes):
        """Render Folium map with earthquakes - IDENTISK med version 1.7"""
        if not earthquakes:
            return
        
        # Konverter til DataFrame
        eq_df = pd.DataFrame(earthquakes)
        
        # KORREKT: Brug create_optimized_map fra version 1.7
        earthquake_map = self.create_optimized_map(eq_df)
        
        if earthquake_map:
            map_data = st_folium(
                earthquake_map, 
                width=950, 
                height=650,
                returned_objects=["last_object_clicked", "last_clicked"],
                key="earthquake_map_start"
            )
            
            # Check for clicks
            if map_data and (map_data.get("last_clicked") or map_data.get("last_object_clicked")):
                # Process click (kunne implementeres senere)
                pass

    def get_earthquake_color_and_size(self, magnitude):
        """Bestemmer farve og størrelse for jordskælv markører baseret på magnitude."""
        if magnitude >= 8.0:
            return 'purple', 15  # Lilla for de største jordskælv
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
            return 'gray', 4

    def get_current_station_key(self):
        """Generer unik nøgle for aktuel station"""
        if not st.session_state.get('selected_station') or not st.session_state.get('selected_earthquake'):
            return None
        
        station = st.session_state.selected_station
        eq = st.session_state.selected_earthquake
        return f"{eq.get('time')}_{station['network']}_{station['station']}"

    def detect_station_change_and_reset(self):
        """Detekterer station skift og nulstiller filter state automatisk"""
        current_key = self.get_current_station_key()
        last_key = st.session_state.get('last_station_key')
        
        if current_key != last_key and current_key is not None:
            filter_keys = ['display_data', 'selected_filter_option', 'ms_result', 'wave_analysis', 'wave_first_load']
            for key in filter_keys:
                if key in st.session_state:
                    del st.session_state[key]
            
            st.session_state.last_station_key = current_key
            print(f"🧹 Auto-reset filter state for new station: {current_key}")
            return True
        return False
    
    def get_filter_display_name(self, selected_filter):
        """Returnerer display navn for filter"""
        filter_names = {
            'raw': 'Original Data',
            'p_waves': 'P-bølge Filter',
            's_waves': 'S-bølge Filter', 
            'surface': 'Overfladebølge Filter',
            'broadband': 'Broadband Filter'
        }
        return filter_names.get(selected_filter, 'Ukendt Filter')

    def create_station_map(self, earthquake, stations):
        """
        Opretter kort med jordskælv og stationer med forbedret zoom og datolinje-håndtering
        """
        try:
            from folium.plugins import Fullscreen
            import math
            
            # Beregn bounds for alle punkter
            all_lats = [earthquake['latitude']] + [s['latitude'] for s in stations]
            all_lons = [earthquake['longitude']] + [s['longitude'] for s in stations]
            
            lat_min, lat_max = min(all_lats), max(all_lats)
            lon_min, lon_max = min(all_lons), max(all_lons)
            
            # FORBEDRET: Håndter datolinje-krydsning
            # Tjek om længdegrader krydser datolinjen (180/-180)
            crosses_dateline = False
            if lon_max - lon_min > 180:
                crosses_dateline = True
                # Konverter negative længdegrader til positive (0-360 system)
                adjusted_lons = []
                for lon in all_lons:
                    if lon < 0:
                        adjusted_lons.append(lon + 360)
                    else:
                        adjusted_lons.append(lon)
                
                lon_min_adj = min(adjusted_lons)
                lon_max_adj = max(adjusted_lons)
                
                # Beregn center i 0-360 system og konverter tilbage
                center_lon_adj = (lon_min_adj + lon_max_adj) / 2
                center_lon = center_lon_adj if center_lon_adj <= 180 else center_lon_adj - 360
            else:
                center_lon = (lon_min + lon_max) / 2
            
            center_lat = (lat_min + lat_max) / 2
            
            # FORBEDRET: Dynamisk zoom baseret på område størrelse
            lat_range = lat_max - lat_min
            lon_range = lon_max - lon_min if not crosses_dateline else lon_max_adj - lon_min_adj
            
            # Beregn passende zoom niveau
            max_range = max(lat_range, lon_range)
            if max_range > 120:
                initial_zoom = 2
            elif max_range > 60:
                initial_zoom = 3
            elif max_range > 30:
                initial_zoom = 4
            elif max_range > 15:
                initial_zoom = 5
            elif max_range > 8:
                initial_zoom = 6
            elif max_range > 4:
                initial_zoom = 7
            else:
                initial_zoom = 8
            
            # Opret kort med forbedrede indstillinger
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=initial_zoom,
                tiles=None,
                scrollWheelZoom=True,
                doubleClickZoom=True,
                dragging=True,
                zoomControl=True,  # Aktivér zoom kontrols
                world_copy_jump=False if crosses_dateline else True,  # Deaktiver ved datolinje
                max_bounds=True,  # Begræns til verdenskort
                min_zoom=1,
                max_zoom=15
            )
            
            # FORSKELLIGE KORTTYPER som base layers
            base_maps = {
                'Topografisk': folium.TileLayer(
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
                    attr='Esri',
                    name='Topografisk',
                    overlay=False,
                    control=True
                ),
                'Lande': folium.TileLayer(
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
                    attr='Esri',
                    name='Lande',
                    overlay=False,
                    control=True
                ),
                'Satellit': folium.TileLayer(
                    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                    attr='Esri',
                    name='Satellit',
                    overlay=False,
                    control=True
                )
            }
            
            # Tilføj alle base maps til kortet
            for map_name, tile_layer in base_maps.items():
                tile_layer.add_to(m)
            
            # Tilføj fullscreen knap
            Fullscreen(
                position='topright',
                title='Fuld skærm',
                title_cancel='Luk fuld skærm',
                force_separate_button=True
            ).add_to(m)
            
            # Tilføj Folium's indbyggede LayerControl
            folium.LayerControl(
                position='topright',
                collapsed=True  # Vis korttype menu som standard
            ).add_to(m)
            
            # FORBEDRET: Intelligent padding og bounds
            if crosses_dateline:
                # Ved datolinje-krydsning: Brug center-baseret zoom i stedet for fit_bounds
                pass  # Brug initial_zoom beregnet ovenfor
            else:
                # Normal bounds beregning med intelligent padding
                lat_padding = max(lat_range * 0.15, 1.0)  # Minimum 1 grad padding
                lon_padding = max(lon_range * 0.15, 1.0)
                
                # Begræns padding for at undgå for store områder
                lat_padding = min(lat_padding, 10.0)
                lon_padding = min(lon_padding, 15.0)
                
                southwest = [max(lat_min - lat_padding, -85), max(lon_min - lon_padding, -180)]
                northeast = [min(lat_max + lat_padding, 85), min(lon_max + lon_padding, 180)]
                
                try:
                    m.fit_bounds([southwest, northeast])
                except:
                    # Fallback hvis fit_bounds fejler
                    pass
            
            # TILFØJ RETNINGSKVADRANTER (kan slås fra)
            if st.session_state.get('show_direction_quadrants', True):
                eq_lat = earthquake['latitude']
                eq_lon = earthquake['longitude']
                
                # Beregn radius for kvadranterne
                max_station_dist = max([s['distance_km'] for s in stations]) if stations else 1000
                radius_km = max_station_dist * 1.2
                radius_deg = radius_km / 111.0
                
                # Begræns radius for at undgå problemer ved poler og datolinje
                radius_deg = min(radius_deg, 45.0)
                
                # Definer kvadranter med farver
                quadrants = [
                    {
                        'name': 'Nord',
                        'bounds': [
                            [eq_lat, eq_lon],
                            [min(eq_lat + radius_deg, 85), eq_lon],
                            [min(eq_lat + radius_deg, 85), eq_lon + radius_deg],
                            [eq_lat, eq_lon + radius_deg]
                        ],
                        'color': 'lightblue',
                        'opacity': 0.25
                    },
                    {
                        'name': 'Øst',
                        'bounds': [
                            [eq_lat, eq_lon],
                            [eq_lat, eq_lon + radius_deg],
                            [max(eq_lat - radius_deg, -85), eq_lon + radius_deg],
                            [max(eq_lat - radius_deg, -85), eq_lon]
                        ],
                        'color': 'lightgreen',
                        'opacity': 0.25
                    },
                    {
                        'name': 'Syd',
                        'bounds': [
                            [eq_lat, eq_lon],
                            [max(eq_lat - radius_deg, -85), eq_lon],
                            [max(eq_lat - radius_deg, -85), eq_lon - radius_deg],
                            [eq_lat, eq_lon - radius_deg]
                        ],
                        'color': 'lightyellow',
                        'opacity': 0.25
                    },
                    {
                        'name': 'Vest',
                        'bounds': [
                            [eq_lat, eq_lon],
                            [eq_lat, eq_lon - radius_deg],
                            [min(eq_lat + radius_deg, 85), eq_lon - radius_deg],
                            [min(eq_lat + radius_deg, 85), eq_lon]
                        ],
                        'color': 'lightcoral',
                        'opacity': 0.25
                    }
                ]
                
                # Tilføj kvadranter med bounds-validering
                for quad in quadrants:
                    try:
                        # Valider at bounds er indenfor gyldige koordinater
                        valid_bounds = []
                        for point in quad['bounds']:
                            lat = max(-85, min(85, point[0]))
                            lon = max(-180, min(180, point[1]))
                            valid_bounds.append([lat, lon])
                        
                        folium.Polygon(
                            locations=valid_bounds,
                            color=quad['color'],
                            fill=True,
                            fillColor=quad['color'],
                            fillOpacity=quad['opacity'],
                            opacity=0.25,
                            weight=1
                        ).add_to(m)
                    except:
                        # Skip denne kvadrant hvis der er problemer
                        continue
                
                # Tilføj kryds ved epicenter (med bounds check)
                safe_radius = min(radius_deg, 45.0)
                
                try:
                    folium.PolyLine(
                        locations=[
                            [max(eq_lat - safe_radius, -85), eq_lon], 
                            [min(eq_lat + safe_radius, 85), eq_lon]
                        ],
                        color='white',
                        weight=1,
                        opacity=0.4,
                        dash_array='5, 5'
                    ).add_to(m)
                    
                    folium.PolyLine(
                        locations=[
                            [eq_lat, max(eq_lon - safe_radius, -180)], 
                            [eq_lat, min(eq_lon + safe_radius, 180)]
                        ],
                        color='white',
                        weight=1,
                        opacity=0.4,
                        dash_array='5, 5'
                    ).add_to(m)
                except:
                    pass  # Skip kryds hvis der er problemer
                
                # Tilføj retningslabels med sikre positioner
                for quad in quadrants:
                    try:
                        label_offset = safe_radius * 0.7
                        if quad['name'] == 'Nord':
                            label_pos = [min(eq_lat + label_offset, 85), eq_lon]
                        elif quad['name'] == 'Øst':
                            label_pos = [eq_lat, min(eq_lon + label_offset, 180)]
                        elif quad['name'] == 'Syd':
                            label_pos = [max(eq_lat - label_offset, -85), eq_lon]
                        else:  # Vest
                            label_pos = [eq_lat, max(eq_lon - label_offset, -180)]
                        
                        folium.Marker(
                            location=label_pos,
                            icon=folium.DivIcon(
                                html=f'''<div style="
                                    font-size: 14px; 
                                    font-weight: bold;
                                    color: {quad['color']}; 
                                    text-shadow: 1px 1px 2px white, -1px -1px 2px white;
                                    text-align: center;
                                ">{quad['name']}</div>''',
                                icon_size=(40, 20),
                                icon_anchor=(20, 10)
                            )
                        ).add_to(m)
                    except:
                        continue
            
            # Tilføj transparente afstandscirkler omkring jordskælv
            for radius_km in [1000, 2000, 3000, 4000, 5000]:
                folium.Circle(
                    location=[earthquake['latitude'], earthquake['longitude']],
                    radius=radius_km * 1000,
                    color='white',
                    weight=1,
                    fill=True,
                    fillOpacity=0.1,
                    opacity=0.4,
                    dash_array='5,5'
                ).add_to(m)
                
                # Tilføj afstandslabel
                lat_offset = radius_km / 111.0
                label_lat = min(earthquake['latitude'] + lat_offset, 85)
                label_lon = earthquake['longitude']
                
                folium.Marker(
                    location=[label_lat, label_lon],
                    icon=folium.DivIcon(
                        html=f'''<div style="
                            font-size: 12px; 
                            font-weight: bold;
                            color: white; 
                            text-shadow: 1px 1px 2px black, -1px -1px 2px black;
                            text-align: center;
                            margin-top: -10px;
                        ">{radius_km} km</div>''',
                        icon_size=(60, 20),
                        icon_anchor=(30, 10)
                    )
                ).add_to(m)
            
            # Tilføj jordskælv som rød stjerne
            folium.Marker(
                location=[earthquake['latitude'], earthquake['longitude']],
                icon=folium.DivIcon(
                    html=f'''<div style="font-size: 28px; text-align: center; line-height: 1;">
                            <span style="color: red; text-shadow: 1px 1px 2px black; display: block; margin-top: -7px;">★</span>
                            </div>''',
                    icon_size=(28, 28),
                    icon_anchor=(14, 14)
                ),
                popup=f"M{earthquake['magnitude']} - {earthquake.get('location', 'Unknown')}",
                tooltip=f"M{earthquake['magnitude']} Jordskælv"
            ).add_to(m)
            
            # TILFØJ STATIONER SOM TREKANTER
            for i, station in enumerate(stations):
                station_id = i + 1
                color = self.get_distance_gradient_color(station['distance_km'])
                
                # Beregn retning for stationen
                lat_diff = station['latitude'] - earthquake['latitude']
                lon_diff = station['longitude'] - earthquake['longitude']
                
                # Simple 8-retninger
                if abs(lat_diff) > abs(lon_diff) * 2:
                    direction = "Nord" if lat_diff > 0 else "Syd"
                elif abs(lon_diff) > abs(lat_diff) * 2:
                    direction = "Øst" if lon_diff > 0 else "Vest"
                else:
                    if lat_diff > 0 and lon_diff > 0:
                        direction = "Nordøst"
                    elif lat_diff > 0 and lon_diff < 0:
                        direction = "Nordvest"
                    elif lat_diff < 0 and lon_diff > 0:
                        direction = "Sydøst"
                    else:
                        direction = "Sydvest"
                
                # Trekant HTML med nummerering
                triangle_html = f'''
                <div style="position: relative; width: 30px; height: 26px;">
                    <!-- Hvid baggrunds-trekant -->
                    <div style="
                        position: absolute;
                        top: 0;
                        left: 50%;
                        transform: translateX(-50%);
                        width: 0; 
                        height: 0; 
                        border-left: 15px solid transparent;
                        border-right: 15px solid transparent;
                        border-bottom: 26px solid white;
                    "></div>
                    <!-- Farvet trekant -->
                    <div style="
                        position: absolute;
                        top: 2px;
                        left: 50%;
                        transform: translateX(-50%);
                        width: 0; 
                        height: 0; 
                        border-left: 13px solid transparent;
                        border-right: 13px solid transparent;
                        border-bottom: 22px solid {color};
                    "></div>
                    <!-- Nummer -->
                    <div style="
                        position: absolute;
                        top: 8px;
                        left: 50%;
                        transform: translateX(-50%);
                        color: white;
                        font-size: 12px;
                        font-weight: bold;
                        text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
                        z-index: 10;
                    ">{station_id}</div>
                </div>
                '''
                
                # Tilføj klikbar cirkel (usynlig)
                folium.CircleMarker(
                    location=[station['latitude'], station['longitude']],
                    radius=15,
                    fillColor=color,
                    color='transparent',
                    weight=0,
                    fillOpacity=0,
                    popup=f"{station['network']}.{station['station']}<br>"
                        f"Afstand: {station['distance_km']:.0f} km<br>"
                        f"Retning: {direction}<br>"
                        f"Klik for at vælge",
                    tooltip=f"{station['network']}.{station['station']} ({station['distance_km']:.0f} km) - {direction}"
                ).add_to(m)
                
                # Tilføj trekant visuelt
                folium.Marker(
                    location=[station['latitude'], station['longitude']],
                    icon=folium.DivIcon(
                        html=triangle_html,
                        icon_size=(30, 26),
                        icon_anchor=(15, 13)
                    ),
                    clickable=False
                ).add_to(m)
            
            return m
            
        except Exception as e:
            st.error(f"Fejl ved oprettelse af kort: {str(e)}")
            return None


    def create_optimized_map(self, earthquakes_df, stations=None):
        """
        Forbedret version af optimized map med korttype vælger
        IDENTISK med original funktionalitet, kun tilføjet korttype menu
        """
        if earthquakes_df.empty:
            return None
        
        # GLOBAL VIEW for startside
        m = folium.Map(
            location=[10, 70],  # Asien centrum
            zoom_start=2,
            tiles=None,  # Tilføj tiles manuelt
            scrollWheelZoom=True,
            doubleClickZoom=True,
            dragging=True,
            zoomControl=False,
            world_copy_jump=True
        )
        
        # FORSKELLIGE KORTTYPER
        base_maps = {
            
            'Topografisk': folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='Topografisk',
                overlay=False,
                control=True
            ),
            'Politisk': folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='Politisk kort',
                overlay=False,
                control=True
            ),
            'Satellit': folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='Satellit',
                overlay=False,
                control=True
            )
        }
        
        # Tilføj alle base maps
        for map_name, tile_layer in base_maps.items():
            tile_layer.add_to(m)
        
        # Sæt standard kort som aktiv
        base_maps['Satellit'].add_to(m)
        
        # Tilføj fullscreen
        folium.plugins.Fullscreen(
            position='topright',
            title='Fuld skærm',
            title_cancel='Luk fuld skærm',
            force_separate_button=True
        ).add_to(m)
        
        
        
        # Standard LayerControl (skjult)
        folium.LayerControl(position='topright', collapsed=True).add_to(m)
        
        # TILFØJ JORDSKÆLV MARKØRER - ORIGINAL KODE
        for idx, eq in earthquakes_df.iterrows():
            color, radius = self.get_earthquake_color_and_size(eq['magnitude'])
            
            # Sikrer rigtig tid - ORIGINAL
            eq_time = ensure_utc_datetime(eq['time'])
            time_str = format_earthquake_time(eq['time']) if eq_time else 'Unknown'
            
            # Normal cirkel markør - ORIGINAL
            folium.CircleMarker(
                location=[eq['latitude'], eq['longitude']],
                radius=radius,
                tooltip=f"M{eq['magnitude']:.1f} - {time_str} (Klik for detaljer)",
                color='black',
                opacity=0.6,
                fillColor=color,
                fillOpacity=0.8,
                weight=1
            ).add_to(m)
        
        # SIGNATURFORKLARING - ORIGINAL
        legend_html = '''
        <div style="position: fixed; 
                    top: 10px; left: 10px; width: 105px; height: 175px; 
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
        </div>
        '''
        
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m

    def render_start_view(self):
        """Render the start view with latest earthquakes - Kortfattet version"""
        # To kolonner layout
        col_text, col_map = st.columns([1, 2])
        
        with col_text:
            # Overskrift
            st.markdown(f"### {texts[st.session_state.language]['welcome_title']}")
            
            # Kort intro tekst
            if st.session_state.language == 'da':
                st.markdown("""
                **GEOSeis**  giver dig mulighed for at:
                - **Analysere** seismiske data fra hundredvis af stationer
                - **Beregne** magnituder og identificere bølgetyper
                - **Eksportere** data til undervisning

                ---

                Start med at udforske de seneste store jordskælv på kortet
                eller brug menuen til venstre for at søge efter specifikke jordskælv.
                """)
            else:
                st.markdown("""
                **GEOseis** lets you:
                - **Analyze** seismic data from hundreds of stations
                - **Calculate** magnitudes and identify wave types
                - **Export** data for educational use

                ---
                
                Start by exploring recent major earthquakes on the map, or use the menu on the left to search for specific events.
                """)
            
            # Quick stats hvis data er hentet
            if 'latest_earthquakes' in st.session_state and st.session_state.latest_earthquakes:
                st.markdown("---")
                num_eq = len(st.session_state.latest_earthquakes)
                if st.session_state.language == 'da':
                    st.info(f"{num_eq} jordskælv M≥6.5 indenfor det seneste år.  ")
                else:
                    st.info(f"{num_eq} earthquakes M≥6.5 last year. ")
            
            
        with col_map:
            # Kort overskrift
            st.markdown(f"#### {texts[st.session_state.language]['welcome_subtitle']}")
            if st.session_state.language == 'da':
                st.markdown("Du kan zoome ind eller maksimere koretet ved at klikke øverst til højre")
            else:
                st.markdown("Zoom in on the map or toggle full screen in the top right corner")
    
            # Hent og vis jordskælv på kort
            if self.data_manager and OBSPY_AVAILABLE:
                # Check cache først
                if 'latest_earthquakes' not in st.session_state or not st.session_state.latest_earthquakes:
                    with st.spinner(texts[st.session_state.language]['loading_earthquakes']):
                        try:
                            # Hent seneste store jordskælv
                            earthquakes = self.data_manager.get_latest_significant_earthquakes(
                                min_magnitude=6.5,
                                days=365
                            )
                            if earthquakes:
                                st.session_state.latest_earthquakes = earthquakes
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
                            earthquakes = None
                else:
                    earthquakes = st.session_state.latest_earthquakes
                
                # Vis kort med jordskælv - BRUG render_earthquake_map_interactive!
                if st.session_state.get('latest_earthquakes'):
                    # Brug den eksisterende interaktive kort funktion
                    self.render_earthquake_map_interactive(st.session_state.latest_earthquakes)
                    
                
                else:
                    if st.session_state.language == 'da':
                        st.info("📍 Ingen nyere jordskælv M≥6.5 fundet.")
                    else:
                        st.info("📍 No recent earthquakes M≥6.5 found.")
            else:
                st.warning("⚠️ Data manager not available.")
                
                
    def get_distance_gradient_color(self, distance_km):
        """Get gradient color based on distance"""
        # Gradient fra grøn (tæt) til rød (langt)
        if distance_km < 1000:
            return "#28a745"  # Grøn
        elif distance_km < 2000:
            return "#ffc107"  # Gul  
        elif distance_km < 3000:
            return "#fd7e14"  # Orange
        else:
            return "#dc3545"  # Rød  
    

    def render_earthquake_map_interactive(self, earthquakes):
        """Render interactive earthquake map for homepage med FORBEDRET klik håndtering"""
        if not earthquakes:
            return
        
        # Konverter til DataFrame
        df = pd.DataFrame(earthquakes)
        
        # Tilføj index til DataFrame for at kunne matche senere
        df.reset_index(inplace=True)
        
        # Opret kort
        earthquake_map = self.create_optimized_map(df)
        
        if earthquake_map:
            # Vis kort
            map_data = st_folium(
                earthquake_map,
                width=775,
                height=525,
                returned_objects=["last_object_clicked", "last_clicked", "bounds"],
                key="home_earthquake_map"
            )
            
            # Process klik på kort med bedre fejlhåndtering
            if map_data:
                                
                clicked_eq = self.process_earthquake_click(map_data, df)
                
                if clicked_eq:
                    st.session_state.selected_earthquake = clicked_eq
                    st.session_state.current_view = 'analysis_stations'
                    # Reset station selection
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    
                    self.toast_manager.show(
                        f"Valgt: M{clicked_eq['magnitude']:.1f} jordskælv", 
                        toast_type='success',
                        duration=2.0
                    )
                    st.rerun()
        
        # Vis tabel under kortet
        st.markdown("### Seneste større jordskælv")
        
        # Table headers
        col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])
        with col1:
            st.markdown("**Lokation**")
        with col2:
            st.markdown("**Dato**")
        with col3:
            st.markdown("**Mag.**")
        with col4:
            st.markdown("**Dybde**")
        with col5:
            st.markdown("**Koordinater**")
        
        # Display earthquakes
        for idx, eq in enumerate(earthquakes[:10]):
            col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])
            
            with col1:
                if st.button(
                    f"{eq.get('location', 'Unknown')[:30]}...",
                    key=f"eq_home_{idx}",
                    use_container_width=True,
                    help=eq.get('location', 'Unknown')
                ):
                    st.session_state.selected_earthquake = eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET til stationsvalg
                    # Reset station selection
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.rerun()
            
            with col2:
                st.text(format_earthquake_time(eq['time']))
            
            with col3:
                magnitude_color = "🔴" if eq['magnitude'] >= 7.0 else "🟠" if eq['magnitude'] >= 6.0 else "🟡"
                st.text(f"{magnitude_color} {eq['magnitude']:.1f}")
            
            with col4:
                st.text(f"{eq.get('depth', 0):.0f} km")
            
            with col5:
                st.text(f"{eq.get('latitude', 0):.1f}°, {eq.get('longitude', 0):.1f}°")


    def process_earthquake_click(self, map_data, earthquakes_df):
        """Process earthquake click from map - ROBUST VERSION"""
        if not map_data:
            return None
        
        # Debug info
        # st.write("Debug - map_data keys:", list(map_data.keys()))
        # if map_data.get("last_object_clicked"):
        #     st.write("Debug - last_object_clicked:", map_data["last_object_clicked"])
        
        clicked_lat = None
        clicked_lon = None
        
        # Metode 1: Check last_object_clicked (folium markers)
        if map_data.get("last_object_clicked"):
            clicked_obj = map_data["last_object_clicked"]
            if isinstance(clicked_obj, dict):
                # Folium bruger nogle gange 'lat'/'lng', andre gange 'latitude'/'longitude'
                clicked_lat = clicked_obj.get("lat") or clicked_obj.get("latitude")
                clicked_lon = clicked_obj.get("lng") or clicked_obj.get("longitude")
        
        # Metode 2: Check last_clicked (general map clicks)
        if clicked_lat is None and map_data.get("last_clicked"):
            clicked = map_data["last_clicked"]
            if isinstance(clicked, dict):
                clicked_lat = clicked.get("lat") or clicked.get("latitude")
                clicked_lon = clicked.get("lng") or clicked.get("longitude")
        
        # Metode 3: Check for coordinates direkte i map_data
        if clicked_lat is None:
            clicked_lat = map_data.get("lat") or map_data.get("latitude")
            clicked_lon = map_data.get("lng") or map_data.get("longitude")
        
        # Hvis vi har koordinater, find nærmeste jordskælv
        if clicked_lat is not None and clicked_lon is not None:
            try:
                closest_eq = None
                min_distance = float('inf')
                
                # Find nærmeste jordskælv
                for idx, eq in earthquakes_df.iterrows():
                    # Beregn afstand (simpel Euclidean distance)
                    lat_diff = eq['latitude'] - clicked_lat
                    lon_diff = eq['longitude'] - clicked_lon
                    distance = (lat_diff**2 + lon_diff**2)**0.5
                    
                    if distance < min_distance:
                        min_distance = distance
                        closest_eq = eq
                
                # Tjek om klikket er tæt nok på et jordskælv
                # 10 grader tolerance er meget generøst, men sikrer at klik registreres
                if closest_eq is not None and min_distance < 10.0:
                    # Konverter til dictionary hvis det er en pandas Series
                    if hasattr(closest_eq, 'to_dict'):
                        earthquake_dict = closest_eq.to_dict()
                    else:
                        earthquake_dict = dict(closest_eq)
                    
                    # Reset station relaterede states
                    st.session_state.selected_station = None
                    st.session_state.station_list = None
                    st.session_state.waveform_data = None
                    
                    return earthquake_dict
                    
            except Exception as e:
                st.error(f"Fejl ved processing af kort klik: {str(e)}")
        
        return None

    def render_analysis_stations_view(self):
        """
        RETTEDE station selection view - eliminerer dobbelt kald
        - Bruger state-baseret conditional rendering
        - Ingen problematiske st.rerun() kald
        - Elegant håndtering af search flow
        """
        
        # Vis breadcrumb navigation
        self.render_breadcrumb_with_title("Stationsvalg")
        
        # Check om et jordskælv er valgt
        if not st.session_state.get('selected_earthquake'):
            st.info("🔍 Vælg først et jordskælv fra startsiden eller søg efter jordskælv i Data menuen")
            
            if st.button("← Gå til startsiden", type="secondary"):
                st.session_state.current_view = 'start'
                st.rerun()
            return
        
        # Hent valgt jordskælv
        eq = st.session_state.selected_earthquake
        
        # SMART STATE MANAGEMENT - undgå dobbelt kald
        
        # 1. Check om vi allerede har stationer
        has_stations = st.session_state.get('station_list') is not None
        
        # 2. Check om search er i gang (men kun vis UI én gang)
        search_in_progress = st.session_state.get('searching_stations', False)
        
        # 3. Hvis search netop er startet, kør søgning ÉN gang
        if search_in_progress and not has_stations and not st.session_state.get('search_executed', False):
            # Marker at search er blevet kørt for at undgå dobbelt execution
            st.session_state.search_executed = True
            
            # Hent search parametre fra session state (sat ved button click)
            min_dist = st.session_state.get('search_min_dist', 1500)
            max_dist = st.session_state.get('search_max_dist', 3000)
            target_stations = st.session_state.get('search_target_stations', 3)
            
            print(f"🎯 EXECUTING SEARCH: {min_dist}-{max_dist}km, {target_stations} stations")
            
            # Kør søgning ÉN gang
            with st.spinner("Finder stationer..."):
                try:
                    stations = self.data_manager.search_stations(
                        earthquake=eq,
                        min_distance_km=min_dist,
                        max_distance_km=max_dist,
                        target_stations=target_stations
                    )
                    
                    if stations and len(stations) > 0:
                        # Success - gem resultater og ryd flags
                        st.session_state.station_list = stations
                        st.session_state.searching_stations = False
                        st.session_state.search_executed = False
                        
                        st.success(f"✅ Fandt {len(stations)} stationer")
                        print(f"🎉 SEARCH SUCCESS: Found {len(stations)} stations")
                        
                        # IKKE st.rerun() - lad Streamlit opdatere naturligt
                        
                    else:
                        # Ingen stationer fundet
                        st.error("❌ Ingen stationer fundet")
                        st.session_state.searching_stations = False
                        st.session_state.search_executed = False
                        
                except Exception as e:
                    # Search fejlede
                    st.error(f"❌ Fejl ved søgning: {str(e)}")
                    st.session_state.searching_stations = False
                    st.session_state.search_executed = False
        
        # RENDER UI baseret på current state
        if has_stations:
            # LAYOUT: Vis stationer (to kolonner)
            self._render_stations_layout(eq)
            
        else:
            # LAYOUT: Vis search interface (to kolonner)
            self._render_search_layout(eq, search_in_progress)


    def _render_search_layout(self, eq, search_in_progress):
        """Render search interface"""
        col1, col2 = st.columns([1, 3])
        
        with col1:
            # Jordskælv info
            st.markdown(
                f"""<div style="font-size: 0.9rem;">
                <span style="color: #E74C3C; font-weight: bold;">VALGT JORDSKÆLV:</span><br>
                <span style="color: #6C757D;">
                Dato: {format_earthquake_time(eq['time'])}<br>
                Magnitude: M{eq['magnitude']:.1f}<br>
                Dybde: {eq.get('depth', 0):.0f} km<br>
                Region: {eq.get('location', 'Unknown')[:30]}
                </span>
                </div>""",
                unsafe_allow_html=True
            )
            
            # Search form
            st.markdown("### 🔍 Søg stationer")
            
            # VIGTIGT: Disable inputs hvis search er i gang
            disabled = search_in_progress
            
            min_dist = st.number_input(
                "Min afstand (km)", 
                value=st.session_state.get('search_min_dist', 1500),
                min_value=500, 
                max_value=10000, 
                step=100,
                disabled=disabled
            )
            
            max_dist = st.number_input(
                "Max afstand (km)", 
                value=st.session_state.get('search_max_dist', 4000),
                min_value=100, 
                max_value=20000, 
                step=100,
                disabled=disabled
            )
            
            target_stations = st.number_input(
                "Antal stationer", 
                value=st.session_state.get('search_target_stations', 6),
                min_value=1, 
                max_value=20,
                disabled=disabled
            )
            
            # Search button
            if search_in_progress:
                st.info("🔄 Søger...")
            else:
                if st.button("🔍 Søg", type="primary", use_container_width=True):
                    # Gem search parametre
                    st.session_state.search_min_dist = min_dist
                    st.session_state.search_max_dist = max_dist
                    st.session_state.search_target_stations = target_stations
                    
                    # Start search
                    st.session_state.searching_stations = True
                    st.session_state.search_executed = False
                    
                    print(f"🚀 SEARCH INITIATED: {min_dist}-{max_dist}km, {target_stations} stations")
                    st.rerun()
        
        with col2:
            # Kort med kun jordskælv
            m = self.create_earthquake_only_map(eq)
            if m:
                st_folium(m, width=700, height=500, key="earthquake_only_map")


    def _render_stations_layout(self, eq):
        """Render stations layout med station liste og kort"""
        stations = st.session_state.station_list
        col1, col2 = st.columns([1, 4])
        
        with col1:
            # Jordskælv info
            st.markdown(
                f"""<div style="font-size: 0.9rem;">
                <span style="color: #E74C3C; font-weight: bold;">VALGT JORDSKÆLV:</span><br>
                <span style="color: #6C757D;">
                Dato: {format_earthquake_time(eq['time'])}<br>
                Magnitude: M{eq['magnitude']:.1f}<br>
                Dybde: {eq.get('depth', 0):.0f} km<br>
                Region: {eq.get('location', 'Unknown')[:30]}
                </span>
                </div>""",
                unsafe_allow_html=True
            )
            
            # Station selection
            st.subheader("Vælg station")
            st.markdown("Klik på kortet eller vælg fra listen nedenfor:")
            
            # Station selectbox
            station_options = [f"{i+1}. {s['network']}.{s['station']} - {s['distance_km']:.0f}km" 
                            for i, s in enumerate(stations)]
            
            selected_option = st.selectbox(
                "Station:",
                options=station_options,
                index=None,
                placeholder="Vælg en station...",
                label_visibility="collapsed"
            )
            
            if selected_option:
                # Find station baseret på valg
                station_idx = int(selected_option.split('.')[0]) - 1
                selected_station = stations[station_idx]
                
                if st.button("Vis seismogram", type="primary", use_container_width=True):
                    st.session_state.selected_station = selected_station
                    
                    # Check cache
                    cache_key = f"{eq.get('time')}_{selected_station['network']}_{selected_station['station']}"
                    if 'waveform_cache' not in st.session_state:
                        st.session_state.waveform_cache = {}
                    
                    if cache_key in st.session_state.waveform_cache:
                        st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                        st.success("📂 Bruger cached data")
                    else:
                        st.session_state.downloading_waveform = True
                        st.session_state.waveform_data = None
                    
                    st.session_state.current_view = 'unified_analysis'
                    st.rerun()
            
            # Søg igen knap
            st.markdown("---")
            
            if st.button("🔍 Søg nye stationer", type="secondary", use_container_width=True):
                # Eksisterende cleanup
                st.session_state.station_list = None
                st.session_state.selected_station = None
                st.session_state.waveform_data = None
                st.session_state.searching_stations = False
                st.session_state.search_executed = False
                
                # TILFØJ - reset station tracking og filter state
                st.session_state.last_station_key = None
                filter_keys = ['display_data', 'selected_filter_option', 'ms_result', 'wave_analysis', 'wave_first_load']
                for key in filter_keys:
                    if key in st.session_state:
                        del st.session_state[key]
                
                print(f"🔄 RESET: Cleared station data for new search")
                st.rerun()
            
        
        with col2:
            # Kort med stationer
            station_map = self.create_station_map(eq, stations)
            
            if station_map:
                map_data = st_folium(
                    station_map,
                    width=800,
                    height=600,
                    returned_objects=["last_object_clicked", "last_clicked"],
                    key="station_selection_map"
                )
                
                # Håndter klik på kort
                if map_data:
                    clicked_station = self.process_station_click(map_data, stations)
                    if clicked_station:
                        st.session_state.selected_station = clicked_station
                        
                        # Check cache
                        cache_key = f"{eq.get('time')}_{clicked_station['network']}_{clicked_station['station']}"
                        if 'waveform_cache' not in st.session_state:
                            st.session_state.waveform_cache = {}
                        
                        if cache_key in st.session_state.waveform_cache:
                            st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                            # ÆNDRET fra toast til success
                            st.success("📂 Bruger cached data")


                        else:
                            st.session_state.downloading_waveform = True
                            st.session_state.waveform_data = None
                        
                        st.session_state.current_view = 'unified_analysis'
                        st.rerun()
            
            # Station info under kortet
            if stations:
                st.markdown(f"**Fundet {len(stations)} stationer**")
                for i, station in enumerate(stations[:5]):  # Vis kun første 5
                    st.markdown(f"{i+1}. **{station['network']}.{station['station']}** - {station['distance_km']:.0f} km")
                
                if len(stations) > 5:
                    st.markdown(f"... og {len(stations) - 5} flere")
  
    def render_data_view(self):
        """Render the data selection and search view"""
        st.markdown(f"## {texts[st.session_state.language]['search_title']}")
        
        # Search form
        with st.form("earthquake_search"):
            st.markdown(f"### {texts[st.session_state.language]['search_criteria']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                mag_range = st.slider(
                    texts[st.session_state.language]['magnitude_range'],
                    min_value=4.0,
                    max_value=9.0,
                    value=st.session_state.magnitude_range,
                    step=0.1,
                    help=texts[st.session_state.language]['magnitude_help']
                )
                
                year_range = st.slider(
                    texts[st.session_state.language]['date_range'],
                    min_value=1990,
                    max_value=datetime.now().year,
                    value=st.session_state.year_range,
                    help=texts[st.session_state.language]['date_help']
                )
            
            with col2:
                depth_range = st.slider(
                    texts[st.session_state.language]['depth_range'],
                    min_value=0,
                    max_value=700,
                    value=st.session_state.depth_range,
                    step=10,
                    help=texts[st.session_state.language]['depth_help']
                )
                
                max_results = st.number_input(
                    texts[st.session_state.language]['max_results'],
                    min_value=1,
                    max_value=500,
                    value=50
                )
            
            submitted = st.form_submit_button(
                texts[st.session_state.language]['search_button'],
                type="primary"
            )
            
            if submitted:
                st.session_state.magnitude_range = mag_range
                st.session_state.year_range = year_range
                st.session_state.depth_range = depth_range
                
                with st.spinner(texts[st.session_state.language]['loading']):
                    import time
                    time.sleep(2)
                
                st.success("Søgning udført!")

     
    def process_station_click(self, map_data, stations):
        """Process station click from map - koordinat baseret"""
        if not map_data:
            return None
        
        clicked_lat = None
        clicked_lon = None
        
        # Prioriteret klik håndtering
        if map_data.get("last_object_clicked"):
            try:
                clicked_obj = map_data["last_object_clicked"]
                if clicked_obj and isinstance(clicked_obj, dict):
                    clicked_lat = clicked_obj.get("lat") or clicked_obj.get("latitude")
                    clicked_lon = clicked_obj.get("lng") or clicked_obj.get("longitude")
            except Exception:
                pass
        
        # Fallback til general click
        if clicked_lat is None and map_data.get("last_clicked"):
            try:
                last_clicked = map_data["last_clicked"]
                if isinstance(last_clicked, dict):
                    clicked_lat = last_clicked.get("lat") or last_clicked.get("latitude")
                    clicked_lon = last_clicked.get("lng") or last_clicked.get("longitude")
            except Exception:
                pass
        
        # Find nærmeste station
        if clicked_lat is not None and clicked_lon is not None:
            closest_station = None
            min_distance = float('inf')
            
            for station in stations:
                distance = ((station['latitude'] - clicked_lat)**2 + 
                        (station['longitude'] - clicked_lon)**2)**0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_station = station
            
            # Tolerance for at matche klik
            if closest_station and min_distance < 5.0:
                return closest_station
        
        return None


    def create_earthquake_only_map(self, earthquake):
        """Opretter kort med kun jordskælv - samme stil som hovedkort"""
        import folium
        
        m = folium.Map(
            location=[earthquake['latitude'], earthquake['longitude']],
            zoom_start=3,
            tiles='Esri_WorldImagery',
            attr=' ',
            scrollWheelZoom=True,
            doubleClickZoom=True,
            dragging=True,
            zoomControl=False
        )
        folium.plugins.Fullscreen(
            position='topright',
            title='Fuld skærm',
            title_cancel='Luk fuld skærm',
            force_separate_button=True
        ).add_to(m)
        
        # Tilføj transparente afstandscirkler
        for radius_km in [1000, 2000, 3000]:
            folium.Circle(
                location=[earthquake['latitude'], earthquake['longitude']],
                radius=radius_km * 1000,
                color='white',
                weight=1,
                fill=True,
                fillOpacity=0.1,
                opacity=0.3,
                dash_array='5,5'
            ).add_to(m)
        
        # Tilføj jordskælv som rød stjerne
        folium.Marker(
            location=[earthquake['latitude'], earthquake['longitude']],
            icon=folium.DivIcon(
                html=f'''<div style="font-size: 28px; text-align: center;">
                        <span style="color: red; text-shadow: 2px 2px 4px black;">★</span>
                        </div>''',
                icon_size=(28, 28),
                icon_anchor=(14, 14)
            ),
            popup=f"M{earthquake['magnitude']} - {earthquake.get('location', 'Unknown')}",
            tooltip=f"M{earthquake['magnitude']} Jordskælv"
        ).add_to(m)
        
        return m

           
#############################################################
#----------------- ANALYSESIDE SAMLET --------------------- #         
#############################################################

    def render_unified_analysis_view(self):
        """
        FORBEDRET version - BEVARER din eksisterende UI struktur
        Tilføjer kun auto-fallback logic - INGEN nye langsomme UI komponenter
        """
        
        # BEVAR din eksisterende breadcrumb navigation
        self.render_breadcrumb_with_title("Analyse")
        
        # BEVAR din eksisterende validation checks
        if not st.session_state.get('selected_station'):
            st.info("Vælg først en station fra Stationsvalg")
            if st.button("← Gå til Stationsvalg", type="secondary"):
                st.session_state.current_view = 'analysis_stations'
                st.rerun()
            return
        
        if not st.session_state.get('waveform_data'):
            # BEVAR din eksisterende download logic
            selected_station = st.session_state.selected_station
            eq = st.session_state.selected_earthquake
            
            # BEVAR din eksisterende cache check
            cache_key = f"{eq.get('time')}_{selected_station['network']}_{selected_station['station']}"
            if 'waveform_cache' not in st.session_state:
                st.session_state.waveform_cache = {}
            
            if cache_key in st.session_state.waveform_cache:
                # BEVAR din eksisterende cached data logic
                st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                st.session_state.current_analysis = st.session_state.waveform_cache[cache_key]
                st.info("📂 Bruger cached data")
                
            # NY: Check om download er failed - AUTO FALLBACK SYSTEM
            elif st.session_state.get('download_failed') == cache_key:
                # Station failed - søg automatisk nye stationer
                print(f"🔄 AUTO FALLBACK: Station failed, searching for alternatives...")
                
                # Håndter failed station og søg nye
                new_stations = self.data_manager.handle_failed_station_download(
                    selected_station, eq
                )
                
                if new_stations and len(new_stations) > 0:
                    # Opdater station liste og vælg bedste nye station
                    st.session_state.station_list = new_stations
                    best_station = new_stations[0]  # Første er bedste pga. sorting
                    st.session_state.selected_station = best_station
                    
                    # Ryd failed flag
                    del st.session_state.download_failed
                    
                    # Vis besked og start ny download
                    st.info(f"🔄 {selected_station['network']}.{selected_station['station']} havde ingen data. Prøver {best_station['network']}.{best_station['station']} i stedet...")
                    
                    # Start download af ny station
                    st.session_state.downloading_waveform = True
                    st.rerun()
                    
                else:
                    # Ingen alternative stationer
                    st.error(f"❌ Ingen data tilgængelig for {selected_station['network']}.{selected_station['station']}")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("🔍 Søg andre stationer", use_container_width=True):
                            # Ryd failed tracking og gå tilbage
                            st.session_state.failed_station_downloads = set()
                            st.session_state.current_view = 'analysis_stations'
                            st.session_state.selected_station = None
                            st.rerun()
                    
                    with col2:
                        if st.button("📅 Vælg andet jordskælv", use_container_width=True):
                            st.session_state.current_view = 'data_search'
                            st.info("💡 Tip: Jordskælv fra 2023-2024 har ofte bedre data tilgængelighed")
                            st.rerun()
                    
                    return
                
            else:
                # BEVAR din eksisterende SMART download logic
                download_key = f"download_{cache_key}"
                
                # BEVAR din eksisterende download state checks
                if st.session_state.get('downloading_waveform_active') == download_key:
                    st.info("⏳ Henter seismogramdata...")
                    return
                
                elif st.session_state.get('downloading_waveform', False):
                    # BEVAR din eksisterende download execution guard
                    st.session_state.downloading_waveform_active = download_key
                    st.session_state.downloading_waveform = False
                    
                    print(f"🌊 STARTING WAVEFORM DOWNLOAD: {selected_station['network']}.{selected_station['station']}")
                    
                    # BEVAR din eksisterende download spinner og logic
                    with st.spinner(f"Henter data fra {selected_station['network']}.{selected_station['station']}..."):
                        try:
                            # BRUG din eksisterende download funktion (nu med forbedringer)
                            waveform_data = self.data_manager.download_waveform_data(
                                earthquake=eq,
                                station=selected_station
                            )
                            
                            if waveform_data:
                                # BEVAR din eksisterende cache og state logic
                                st.session_state.waveform_cache[cache_key] = waveform_data
                                st.session_state.waveform_data = waveform_data
                                st.session_state.current_analysis = waveform_data
                                
                                print(f"✅ WAVEFORM SUCCESS: Downloaded and cached data")
                                st.session_state.downloading_waveform = False
                                
                            else:
                                st.error("❌ Kunne ikke hente data for denne station")
                                print(f"❌ WAVEFORM FAILED: No data returned")
                                # Auto-fallback vil blive håndteret i næste render
                                
                        except Exception as e:
                            st.error(f"❌ Download fejl: {str(e)}")
                            print(f"❌ WAVEFORM ERROR: {e}")
                            
                        finally:
                            # BEVAR din eksisterende cleanup
                            if st.session_state.get('downloading_waveform_active') == download_key:
                                del st.session_state.downloading_waveform_active
                                print(f"🔓 DOWNLOAD: Cleared download flag")
                    
                    # BEVAR din eksisterende rerun logic
                    if st.session_state.get('waveform_data'):
                        st.rerun()
                    return
                
                else:
                    # BEVAR din eksisterende info message
                    st.info("👆 Seismogramdata vil blive hentet automatisk...")
                    return
        self.detect_station_change_and_reset()

        
        # BEVAR din eksisterende analysis interface - INGEN ændringer
        station = st.session_state.selected_station
        eq = st.session_state.selected_earthquake
        waveform_data = st.session_state.waveform_data
        sampling_rate = waveform_data.get('sampling_rate', 100)
        
        # AUTOMATISK MS BEREGNING ved første besøg
        if 'ms_result' not in st.session_state:
            # Sæt standard værdier
            st.session_state.ms_reference_period = 20.0
            expected_rayleigh = station.get('rayleigh_arrival', station.get('surface_arrival', 300.0))
            st.session_state.ms_window_start = expected_rayleigh
            st.session_state.ms_window_duration = 600.0
            
            # Udfør automatisk beregning
            self._calculate_ms_magnitude(
                waveform_data, station, eq, 
                20.0,  # Standard periode
                expected_rayleigh,  # Start ved forventet Rayleigh
                600.0,  # 10 minutters vindue
                True,   # Med filter
                sampling_rate
            )
        
        # Opret faner
        tab1, tab2, tab3, tab4 = st.tabs([
            " + Seismogram  ", 
            " + Magnitude  ", 
            " + Beregningsdetaljer ",
            " + Bølgekomponenter  "
        ])
        
        # FANE 1: SEISMOGRAM
        with tab1:
            # Filter valg
            col1, col2 = st.columns([8, 2])
            with col1:
                # Plot seismogram med interaktive kontroller
                self._plot_seismogram_with_controls(
                    st.session_state.get('display_data', waveform_data),
                    station, height=500
                )
            
            
            with col2:
                filter_options = {
                    'raw': 'Original data',
                    'p_waves': 'P-bølger (1-10 Hz)',
                    's_waves': 'S-bølger (0.5-5 Hz)',
                    'surface': 'Overfladebølger (0.02-0.5 Hz)'
                }
                
                selected_filter = st.selectbox(
                    "Filter:",
                    options=list(filter_options.keys()),
                    format_func=lambda x: filter_options[x],
                    index=list(filter_options.keys()).index(st.session_state.get('selected_filter_option', 'raw')),
                    key='seismo_filter_select'
                )
            
                if st.button("Anvend filter", use_container_width=True):
                    with st.spinner("Processerer..."):
                        try:
                            filter_type = None if selected_filter == 'raw' else selected_filter
                            
                            if filter_type is None:
                                if 'display_data' in st.session_state:
                                    del st.session_state.display_data
                                if 'selected_filter_option' in st.session_state:
                                    del st.session_state.selected_filter_option
                                st.success("✨ Viser original data")
                            else:
                                # Eksisterende filter kode...
                                processed_data = self.processor.process_waveform_with_filtering(
                                    waveform_data,
                                    filter_type=filter_type,
                                    remove_spikes=True,
                                    calculate_noise=True
                                )
                                
                                if processed_data:
                                    st.session_state.selected_filter_option = selected_filter
                                    display_data = waveform_data.copy()
                                    if 'filtered_data' in processed_data and processed_data['filtered_data']:
                                        display_data['displacement_data'] = processed_data['filtered_data']
                                    st.session_state.display_data = display_data
                            
                            st.rerun()
                                    
                        except Exception as e:
                            st.error(f"Fejl: {str(e)}")
            # Hjælpetekst
                with st.expander("ℹ️ Sådan bruger du seismogrammet", expanded=False):
                    st.markdown("""
                    **Interaktiv visualisering:**
                    - Brug kontrolpanelet i plottet til at vælge komponenter og visningsindstillinger
                    - Klik på legend-elementer for at skjule/vise komponenter
                    - Zoom ved at markere et område med musen
                    - Pan ved at holde shift nede og trække
                    - Dobbeltklik for at nulstille zoom
                    - Klik på fuldskærm-knappen for større visning
                    - Du kan downloade grafen ved at klikke på "foto-knappen"
                    
                    **Ms vindue:**
                    Det gule område viser tidsvinduet brugt til Ms beregning. Det starter ved den forventede 
                    Rayleigh-bølge ankomst ({station.get('rayleigh_arrival', 300):.0f} s) og varer 10 minutter.
                    """)
        # FANE 2: MAGNITUDE
        with tab2:
            col_left, col_right = st.columns([1, 2])
            
            with col_left:
                # Resultat header
                if st.session_state.get('ms_result') is not None:
                    ms_value = st.session_state.ms_result
                    
                    st.markdown(
                        f"""<div style='background-color: #e8f4fd; padding: 10px; border-radius: 5px; text-align: center;'>
                        <div style='font-size: 0.9rem; color: #666;'>Beregnet Ms</div>
                        <div style='font-size: 2rem; font-weight: bold; color: #0066cc;'>{ms_value:.1f}</div>
                        </div>""",
                        unsafe_allow_html=True
                    )
                    
                    delta = ms_value - eq.get('magnitude', 0)
                    color = "#28a745" if abs(delta) < 0.3 else "#ffc107" if abs(delta) < 0.5 else "#dc3545"
                    st.markdown(
                        f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; text-align: center;'>
                        <div style='font-size: 0.9rem; color: #666;'>Afvigelse</div>
                        <div style='font-size: 2rem; font-weight: bold; color: {color};'>{delta:+.1f}</div>
                        </div>""",
                        unsafe_allow_html=True
                    )
                    
                #st.markdown("### Indstillinger")
                # Filter
                apply_ms_filter = st.checkbox(
                    "Anvend overfladebølgefilter (anbefales)",
                    value=True,
                    help="Båndpasfilter 0.02-0.5 Hz"
                )
            
                
                # Analysevindue
                st.markdown("**Analysevindue**")
                expected_rayleigh = station.get('rayleigh_arrival', station.get('surface_arrival', 300.0))
                
                col1, col2 = st.columns(2)
                with col1:
                    window_start = st.number_input(
                        "Start (s)",
                        min_value=0.0,
                        max_value=3600.0,
                        value=st.session_state.get('ms_window_start', expected_rayleigh),
                        step=10.0,
                        help=f"Forventet Rayleigh: {expected_rayleigh:.0f} s"
                    )
                with col2:
                    window_duration = st.number_input(
                        "Varighed (s)",
                        min_value=60.0,
                        max_value=1200.0,
                        value=st.session_state.get('ms_window_duration', 600.0),
                        step=60.0
                    )
                
                st.session_state.ms_window_start = window_start
                st.session_state.ms_window_duration = window_duration
                
                #
                
                col1, col2 = st.columns(2)
                
                with col1:
                    # Måleperiode
                    st.markdown("**Måleperiode**")
                    reference_period = st.number_input(
                        "T (sekunder):",
                        min_value=10.0,
                        max_value=30.0,
                        value=st.session_state.get('ms_reference_period', 20.0),
                        step=0.5,
                        format="%.1f",
                        label_visibility="collapsed"
                    )
                    st.caption("IASPEI standard: 18-22 s")
                
                with col2:
                    st.markdown(" ")
                    # Custom CSS for at matche number_input styling
                    st.markdown("""
                    <style>
                        /* Style update button to match number inputs */
                        div[data-testid="stButton"] > button {
                            background-color: #f0f2f6;
                            border: 1px solid #d0d2d6;
                            height: 38px !important;!important;
                            border-radius: 0.25rem;!important;
                            padding: 0.0.25rem 0.5rem;!important;
                            font-size: 16px;
                            font-weight: 400;
                            color: #262730;
                            width: 100%;
                            transition: all 0.2s;
                        }
                        
                        div[data-testid="stButton"] > button:hover {
                            background-color: #e0e2e6;
                            border-color: #b0b2b6;
                        }
                    </style>
                    """, unsafe_allow_html=True)

                    # Knappen
                    if st.button("↻ Opdater Ms", key="update_ms_styled"):
                        self._calculate_ms_magnitude(
                            waveform_data, station, eq, 
                            reference_period, window_start, window_duration,
                            apply_ms_filter, sampling_rate
                        )
                        st.rerun()
                        pass
                    
                st.markdown("---")
                # Validerings note
                if distance_km := station.get('distance_km', 0):
                    if distance_km < 2000 or distance_km > 16000 or eq.get('depth', 0) > 60:
                        st.markdown("Bemærk advarsel - se under 'Beregningsdetaljer' ")
            
            with col_right:
                # Plot seismogram med interaktive kontroller
                self._plot_seismogram_with_controls(
                    st.session_state.get('display_data', waveform_data),
                    station,
                    height=300
                )
                
                self._render_fft_analysis_highres(
                    waveform_data, sampling_rate, 
                    window_start, window_duration,
                    height=300
                )
                
        
        # FANE 3: BEREGNINGSDETALJER
        with tab3:
            if st.session_state.get('ms_result') is not None and st.session_state.get('ms_explanation'):
                self._render_comprehensive_ms_explanation(
                    st.session_state.ms_explanation,
                    station, eq
                )
            else:
                st.info("Udfør først en Ms beregning under 'Magnitude' fanen")
        
        # FANE 4: BØLGEANALYSE
        with tab4:
            self._render_enhanced_wave_analysis(waveform_data, station)


    def get_filter_status(self):
        """Henter filter status fra session state"""
        selected_filter = st.session_state.get('selected_filter_option', 'raw')
        filter_names = {
            'raw': 'Raw Data',
            'p_waves': 'P-waves Filter',
            's_waves': 'S-waves Filter', 
            'surface': 'Surface Waves Filter',
            'broadband': 'Broadband Filter'
        }
        return filter_names.get(selected_filter, 'Unknown Filter')

    def get_sampling_rate(self):
        """Henter aktuel sampling rate"""
        if 'display_data' in st.session_state:
            waveform_data = st.session_state.display_data
        else:
            waveform_data = st.session_state.get('waveform_data', {})
        
        # Check for high-res data
        has_highres = any(key.startswith('sampling_rate_') for key in waveform_data.keys())
        if has_highres:
            max_rate = max([float(v) for k, v in waveform_data.items() if k.startswith('sampling_rate_')])
            return max_rate
        
        return waveform_data.get('sampling_rate', 100.0)


    def _plot_seismogram_with_controls(self, waveform_data, station, height=600):
        """Plot seismogram med interaktive kontroller integreret i plottet"""
        
        # TILFØJ DETTE - auto-detect station change
        station_changed = self.detect_station_change_and_reset()
        
        # ÆNDRING - brug smart data source selection
        if st.session_state.get('display_data') and not station_changed:
            current_data = st.session_state.display_data
            is_filtered = True
        else:
            current_data = waveform_data
            is_filtered = False
        
        # ÆNDRING - brug current_data i stedet for waveform_data
        displacement_data = current_data.get('displacement_data', {})
        if not displacement_data:
            st.error("Ingen displacement data tilgængelig")
            return
        
        time_array = current_data.get('time', np.array([]))  # ÆNDRET fra waveform_data
        
        # TILFØJ - vis filter status
        if is_filtered:
            filter_name = self.get_filter_display_name(st.session_state.get('selected_filter_option', 'raw'))
        #    st.info(f" Viser data med {filter_name}")
        
        # SIMPEL X-AKSE RANGE - start ved -30s, slut ved slutning af data
        if len(time_array) > 0:
            x_start = -30  # Start 30 sekunder før jordskælv
            x_end = time_array[-1]  # Slut ved slutning af datasæt
        else:
            # Fallback hvis ingen time data
            x_start = -30
            x_end = 1800  # 30 minutter default
        
        # Opret figure med updatemenus for kontroller
        fig = go.Figure()
        
        # Plot alle komponenter (synlighed styres af buttons)
        components = {
            'north': {'name': 'Nord', 'color': '#dc3545', 'visible': True},
            'east': {'name': 'Øst', 'color': '#28a745', 'visible': True},
            'vertical': {'name': 'Vertikal', 'color': '#0056b3', 'visible': True}
        }
        
        for comp_name, comp_info in components.items():
            if comp_name in displacement_data:
                comp_data = displacement_data[comp_name]
                
                if len(time_array) >= len(comp_data):
                    x_data = time_array[:len(comp_data)]
                else:
                    # ÆNDRET - brug current_data i stedet for waveform_data
                    sampling_rate = current_data.get('sampling_rate', 100)
                    x_data = np.arange(len(comp_data)) / sampling_rate
                
                fig.add_trace(go.Scatter(
                    x=x_data,
                    y=comp_data,
                    mode='lines',
                    name=comp_info['name'],
                    line=dict(color=comp_info['color'], width=1.5),
                    visible=comp_info['visible']
                ))
        
        # Tilføj arrival markers
        arrivals = [
            {'time': station.get('p_arrival'), 'name': 'P', 'color': 'red', 'dash': 'dash'},
            {'time': station.get('s_arrival'), 'name': 'S', 'color': 'blue', 'dash': 'dash'},
            {'time': station.get('love_arrival'), 'name': 'Love', 'color': 'purple', 'dash': 'dot'},
            {'time': station.get('rayleigh_arrival'), 'name': 'Rayleigh', 'color': 'green', 'dash': 'dot'}
        ]
        
        for arrival in arrivals:
            if arrival['time']:
                fig.add_vline(
                    x=arrival['time'],
                    line_dash=arrival['dash'],
                    line_color=arrival['color'],
                    annotation_text=arrival['name'],
                    annotation_position="top",
                    visible=True
                )
        
        # Tilføj Ms vindue
        if st.session_state.get('ms_window'):
            window_info = st.session_state.ms_window
            window_start = window_info.get('start', 0)
            window_duration = window_info.get('duration', 600)
            
            fig.add_vrect(
                x0=window_start,
                x1=window_start + window_duration,
                fillcolor="rgba(255,193,7,0.1)",
                layer="below",
                line=dict(color="#ffc107", width=1, dash="dot"),
                annotation_text="Ms vindue",
                annotation_position="top",
                visible=True
            )
        
        # Tilføj jordskælv marker
        fig.add_vline(
            x=0,
            line_width=1,
            line_dash="dot",
            line_color="black",
            annotation_text="Jordskælv",
            annotation_position="top"
        )
        
        # Layout med justeret x-akse
        eq = st.session_state.get('selected_earthquake', {})
        eq_time_str = str(eq.get('time', '')) if eq else ''
        if eq_time_str and len(eq_time_str) >= 10:
            try:
                year, month, day = eq_time_str[:10].split('-')
                months = ['jan', 'feb', 'mar', 'apr', 'maj', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dec']
                danish_date = f"{int(day)}. {months[int(month)-1]} {year}"
            except:
                danish_date = eq_time_str[:10]
        else:
            danish_date = ""
        
        fig.update_layout(
            title={
                'text': f"Earthquake: M{eq.get('magnitude', 0):.1f} ({danish_date}) - Station: {station['network']}.{station['station']} ({station['distance_km']:.0f} km)  - {self.get_filter_status()} - {self.get_sampling_rate():.1f} Hz",
                'font': {'size': 16}
            },
            xaxis_title="Tid siden jordskælv (s)",
            yaxis_title="Forskydning (mm)",
            xaxis=dict(
                range=[x_start, x_end],  # Start ved -30s, slut ved slutning af data
            ),
            height=height,
            hovermode='x unified',
            legend=dict(
                orientation="v",        # Lodret orientering
                yanchor="top",         # Forankret til toppen
                y=0.95,                # 95% fra bunden (inde på grafen)
                xanchor="right",       # Forankret til højre
                x=0.98,                # 98% fra venstre (tæt på højre kant)
                bgcolor="rgba(255, 255, 255, 0.8)",  # Hvid baggrund med transparens
                bordercolor="rgba(0, 0, 0, 0.2)",    # Grå kant
                borderwidth=1,         # Kant tykkelse
                font=dict(size=12)     # Font størrelse
            ),
            showlegend=True,
            margin=dict(t=50, b=50, l=50, r=50)
        )
        
        st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                'displayModeBar': True,
                'displaylogo': False,
                'modeBarButtonsToRemove': [],  # Behold alle knapper
                'modeBarPosition': 'topright',  # Position
                'modeBarOrientation': 'v',      # Lodret orientering
                'toImageButtonOptions': {
                    'format': 'png',
                    'filename': f'seismogram_{station["network"]}_{station["station"]}',
                    'height': 600,
                    'width': 1200,
                    'scale': 2  # Højere opløsning
                }
            }
        )       



    def _render_fft_analysis_highres(self, waveform_data, sampling_rate, window_start, window_duration, height=350):
        """FFT analyse med højeste tilgængelige opløsning"""
        
        # TILFØJ OVERSKRIFT OG TOGGLE FØRST
        col1, col2 = st.columns([3, 1])
        with col2:
            # Toggle for visning
            st.markdown("### Frekvensanalyse")
            st.caption("FFT analyse af overfladebølge-vinduet viser energifordelingen over forskellige perioder")
        
            show_individual = st.checkbox("Vis komponenter", value=False, key="fft_toggle")
        with col1:
            try:
                # Check for high-resolution data
                if 'original_data' in waveform_data and 'displacement' in waveform_data['original_data']:
                    st.info("Bruger høj-opløsnings data til FFT analyse")
                    data_source = waveform_data['original_data']['displacement']
                else:
                    data_source = waveform_data.get('displacement_data', {})
                
                time_array = waveform_data.get('time', [])
                
                # Vindue indekser
                start_idx = int(window_start * sampling_rate)
                end_idx = int((window_start + window_duration) * sampling_rate)
                
                # Plot med dynamisk titel
                fig = go.Figure()
                
                if show_individual:
                    # Plot hver komponent
                    components = {
                        'north': {'name': 'Nord', 'color': '#dc3545'},
                        'east': {'name': 'Øst', 'color': '#28a745'},
                        'vertical': {'name': 'Vertikal', 'color': '#0056b3'}
                    }
                    plot_title = "FFT Spektrum - Individuelle Komponenter"
                    
                    for comp_name, comp_info in components.items():
                        if comp_name in data_source:
                            comp_data = data_source[comp_name]
                            # Håndter high-res data struktur
                            if isinstance(comp_data, dict) and 'data' in comp_data:
                                comp_data = comp_data['data']
                                comp_rate = comp_data.get('sampling_rate', sampling_rate)
                            else:
                                comp_rate = sampling_rate
                            
                            if start_idx < len(comp_data) and end_idx <= len(comp_data):
                                windowed_data = comp_data[start_idx:end_idx]
                                
                                # FFT med korrekt sampling rate
                                N = len(windowed_data)
                                yf = fft(windowed_data - np.mean(windowed_data))
                                xf = fftfreq(N, 1/comp_rate)[:N//2]
                                power = 2.0/N * np.abs(yf[:N//2])
                                
                                # Til perioder
                                valid_mask = xf > 0
                                periods = 1.0 / xf[valid_mask]
                                
                                fig.add_trace(go.Scatter(
                                    x=periods,
                                    y=power[valid_mask],
                                    mode='lines',
                                    name=comp_info['name'],
                                    line=dict(color=comp_info['color'], width=1.5)
                                ))
                else:
                    # Samlet energi
                    plot_title = "FFT Spektrum - Samlet Energi"
                    total_energy = None
                    valid_periods = None
                    
                    for comp_name in ['north', 'east', 'vertical']:
                        if comp_name in data_source:
                            comp_data = data_source[comp_name]
                            # Håndter high-res data struktur
                            if isinstance(comp_data, dict) and 'data' in comp_data:
                                comp_data = comp_data['data']
                                comp_rate = comp_data.get('sampling_rate', sampling_rate)
                            else:
                                comp_rate = sampling_rate
                            
                            if start_idx < len(comp_data) and end_idx <= len(comp_data):
                                windowed_data = comp_data[start_idx:end_idx]
                                
                                # FFT
                                N = len(windowed_data)
                                yf = fft(windowed_data - np.mean(windowed_data))
                                xf = fftfreq(N, 1/comp_rate)[:N//2]
                                power = np.abs(yf[:N//2])**2
                                
                                valid_mask = xf > 0
                                periods = 1.0 / xf[valid_mask]
                                
                                if total_energy is None:
                                    total_energy = power[valid_mask]
                                    valid_periods = periods
                                else:
                                    min_len = min(len(total_energy), len(power[valid_mask]))
                                    total_energy[:min_len] += power[valid_mask][:min_len]
                    
                    if total_energy is not None:
                        total_amplitude = np.sqrt(total_energy / 3)
                        
                        fig.add_trace(go.Scatter(
                            x=valid_periods,
                            y=total_amplitude,
                            mode='lines',
                            name='Samlet energi',
                            line=dict(color='#6610f2', width=2),
                            fill='tozeroy',
                            fillcolor='rgba(102, 16, 242, 0.1)'
                        ))
                
                # Marker reference periode
                fig.add_vline(
                    x=st.session_state.get('ms_reference_period', 20),
                    line_dash="dash",
                    line_color="red",
                    annotation_text=f"T = {st.session_state.get('ms_reference_period', 20)}s"
                )
                
                # Layout med titel og dynamisk højde
                all_y = []
                for trace in fig.data:
                    if hasattr(trace, 'y') and trace.y is not None:
                        all_y.extend(trace.y)
                
                y_max = max(all_y) * 1.2 if all_y else 1
                
                fig.update_layout(
                    title={
                        'text': plot_title,
                        'font': {'size': 14},
                        'x': 0.5,  # Centrer titlen
                        'xanchor': 'center'
                    },
                    xaxis_title="Periode (sekunder)",
                    yaxis_title="Amplitude" if show_individual else "Energi",
                    height=height,  # BRUGER HEIGHT PARAMETER
                    xaxis=dict(
                        range=[5, 35],
                        tickmode='linear',
                        tick0=5,
                        dtick=5
                    ),
                    yaxis=dict(range=[0, y_max]),
                    showlegend=show_individual,  # Vis kun legend ved individuelle komponenter
                    legend=dict(
                        orientation="v",
                        yanchor="top",
                        y=0.95,
                        xanchor="right",
                        x=0.98,
                        bgcolor="rgba(255, 255, 255, 0.8)",
                        bordercolor="rgba(0, 0, 0, 0.2)",
                        borderwidth=1,
                        font=dict(size=12)
                    ),
                    margin=dict(t=40, b=40, l=40, r=40)  # Mere plads til titel
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # TILFØJ FORKLARENDE TEKST UNDER GRAFEN
                if show_individual:
                    st.caption("🔍 Blå: Vertikal komponent | Rød: Nord komponent | Grøn: Øst komponent")
                else:
                    st.caption("🔍 Samlet energi fra alle tre komponenter kombineret")
                    
            except Exception as e:
                st.error(f"FFT fejl: {str(e)}")
        
        
        


    

    


    def _render_comprehensive_ms_explanation(self, explanation, station, eq):
        """Omfattende forklaring af Ms beregning med pædagogisk gennemgang"""
        
        st.markdown("#### Ms Magnitude - gennemgang af beregning")
        
        # Introduktion
        with st.expander("Hvad er Ms magnitude?", expanded=False):
            st.markdown("""
            **Surface wave magnitude (Ms)** er en magnitudeskala specifikt designet til at måle størrelsen 
            af jordskælv baseret på overfladebølgernes amplitude. Den blev udviklet fordi:
            
            - Overfladebølger har den største amplitude og er derfor lette at måle
            - De rejser langs jordoverfladen og dæmpes mindre end krops-bølger
            - De har lang periode (typisk 20 sekunder) hvilket gør dem ideelle til måling
            
            Ms er særligt velegnet til:
            - Jordskælv mellem magnitude 5.0 og 8.0
            - Overfladiske jordskælv (< 60 km dybde)
            - Afstande mellem 200 og 16,000 km
            """)
        
        # Formel forklaring
        with st.expander("IASPEI 2013 Formlen", expanded=False):
            st.markdown("#### Den grundlæggende formel:")
            st.latex(r"Ms = \log_{10}\left(\frac{A}{T}\right) + 1.66 \times \log_{10}(\Delta) + 3.3")
            
            st.markdown("""
            **Forklaring af hver term:**
            
            **A (Amplitude):**
            - Måles i mikrometer (μm)
            - Den maksimale forskydning jorden bevæger sig under overfladebølgens passage
            - Måles som zero-to-peak (fra nul-linjen til toppen)
            - Kan måles på vertikal eller horisontal komponent
            
            **T (Periode):**
            - Måles i sekunder
            - Tiden mellem to på hinanden følgende bølgetoppe
            - Standard er 20 sekunder (IASPEI anbefaling)
            - Kan variere mellem 18-22 sekunder
            
            **Δ (Afstand):**
            - Måles i grader (°)
            - Vinkelafstanden mellem jordskælv og seismograf
            - 1° ≈ 111.2 km ved ækvator
            - Bruges til at korrigere for geometrisk spredning
            
            **Konstanterne:**
            - **1.66**: Geometrisk spredningsfaktor (empirisk bestemt)
            - **3.3**: Kalibreringskonstant for at matche andre magnitudeskalaer
            """)
        
        # Din beregning
        with st.expander("Din Ms Beregning", expanded=True):
            st.markdown("#### Step 1: Målte værdier")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("** Amplituder (μm):**")
                amp = explanation['amplitudes']
                st.write(f"• Nord: {amp['north']:.1f}")
                st.write(f"• Øst: {amp['east']:.1f}")
                st.write(f"• Vertikal: {amp['vertical']:.1f}")
                st.write(f"• Horisontal vektor: {amp['horizontal']:.1f}")
                st.success(f"Valgt: {amp['used']:.1f} μm ({explanation['used_component']})")
            
            with col2:
                st.markdown("** Parametre:**")
                params = explanation['parameters']
                st.write(f"• Periode (T): {params['period']:.1f} s")
                st.write(f"• Afstand: {params['distance_km']:.0f} km")
                st.write(f"• Afstand: {params['distance_deg']:.2f}°")
                st.write(f"• Dybde: {eq.get('depth', 0):.0f} km")
            
            with col3:
                st.markdown("** Filter:**")
                filt = explanation['filter']
                if filt['applied']:
                    st.write(f"• Type: Båndpas")
                    st.write(f"• Område: {filt['low_freq']:.3f}-{filt['high_freq']:.3f} Hz")
                    st.write(f"• Periode: {1/filt['high_freq']:.0f}-{1/filt['low_freq']:.0f} s")
                else:
                    st.write("• Ingen filtrering anvendt")
            
            st.markdown("#### Step 2: Indsæt i formlen")
            
            calc = explanation['calculation']
            
            # Vis beregning trin for trin
            st.markdown("**Beregn amplitude/periode forholdet:**")
            st.latex(f"\\frac{{A}}{{T}} = \\frac{{{amp['used']:.1f}}}{{{params['period']:.1f}}} = {calc['amplitude_period_ratio']:.2f}")
            
            st.markdown("**Tag logaritmen:**")
            st.latex(f"\\log_{{10}}\\left(\\frac{{A}}{{T}}\\right) = \\log_{{10}}({calc['amplitude_period_ratio']:.2f}) = {calc['log_amp_period']:.4f}")
            
            st.markdown("**Beregn afstandsleddet:**")
            st.latex(f"1.66 \\times \\log_{{10}}(\\Delta) = 1.66 \\times \\log_{{10}}({params['distance_deg']:.2f}) = {calc['distance_term']:.4f}")
            
            st.markdown("**Saml det hele:**")
            st.latex(f"Ms = {calc['log_amp_period']:.4f} + {calc['distance_term']:.4f} + 3.3 = {calc['raw_result']:.2f}")
        
        # Korrektioner
        has_corrections = (explanation.get('distance_correction', {}).get('applied') or 
                        explanation.get('depth_correction', {}).get('applied'))
        
        if has_corrections:
            with st.expander("Anvendte korrektioner", expanded=True):
                st.markdown("### Hvorfor korrektioner?")
                st.markdown("""
                IASPEI formlen er kalibreret for 'ideelle' forhold:
                - Afstand > 2000 km (fuldt udviklede overfladebølger)
                - Overfladiske jordskælv (< 50 km dybde)
                
                Når disse betingelser ikke er opfyldt, anvendes empiriske korrektioner.
                """)
                
                if explanation.get('distance_correction', {}).get('applied'):
                    st.markdown("### Afstandskorrektion")
                    dc = explanation['distance_correction']
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.info(f"""
                        **Din afstand: {dc['distance_km']:.0f} km < 2000 km**
                        
                        Ved korte afstande er Rayleigh-bølgerne ikke fuldt udviklede, 
                        hvilket giver lavere amplituder end forventet.
                        """)
                    
                    with col2:
                        st.markdown("**Korrektion:**")
                        st.latex(f"\\Delta Ms = +0.3 \\times \\frac{{2000 - {dc['distance_km']:.0f}}}{{2000}} = +{dc['correction']:.3f}")
                        st.success(f"Korrigeret værdi: {calc['raw_result']:.2f} + {dc['correction']:.3f} = {calc['raw_result'] + dc['correction']:.2f}")
                
                if explanation.get('depth_correction', {}).get('applied'):
                    st.markdown("### 🌊 Dybdekorrektion")
                    dp = explanation['depth_correction']
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.warning(f"""
                        **Jordskælvsdybde: {dp['depth_km']:.0f} km > 50 km**
                        
                        Dybe jordskælv genererer svagere overfladebølger fordi 
                        mere energi forbliver fanget i dybden.
                        """)
                    
                    with col2:
                        st.markdown("**Korrektion:**")
                        st.latex(f"\\Delta Ms = -0.0035 \\times ({dp['depth_km']:.0f} - 50) = {dp['correction']:.3f}")
                        current = calc['raw_result'] + explanation.get('distance_correction', {}).get('correction', 0)
                        st.success(f"Korrigeret værdi: {current:.2f} + {dp['correction']:.3f} = {current + dp['correction']:.2f}")
        
        # Final resultat og validering
        with st.expander("✅ Endeligt resultat og validering", expanded=True):
            col1, col2 = st.columns(2)
            
            with col1:
                
                st.markdown("Sammenligning:")
                official = eq.get('magnitude', 0)
                diff = explanation['magnitude'] - official
                
                if abs(diff) < 0.3:
                    st.success(f"Officiel magnitude: M{official:.1f} (Δ = {diff:+.1f}) ✅")
                    st.markdown("Fremragende overensstemmelse!")
                elif abs(diff) < 0.5:
                    st.warning(f"Officiel magnitude: M{official:.1f} (Δ = {diff:+.1f}) ⚠️")
                    st.markdown("Acceptabel overensstemmelse")
                else:
                    st.error(f"Officiel magnitude: M{official:.1f} (Δ = {diff:+.1f}) ❌")
                    st.markdown("Stor afvigelse - check data kvalitet")
            
            with col2:
                st.markdown("Validering:")
                
                # Check alle validerings issues
                issues = explanation.get('validation', {}).get('issues', [])
                
                if not issues:
                    st.success("✅ Alle parametre inden for anbefalede grænser")
                else:
                    for issue in issues:
                        if issue['type'] == 'distance':
                            st.warning(f"**Afstand:** {issue['message']}")
                            st.caption(issue['detail'])
                        elif issue['type'] == 'depth':
                            st.warning(f"**Dybde:** {issue['message']}")
                            st.caption(issue['detail'])

    def _render_enhanced_wave_analysis(self, waveform_data, station):
        """Bølgeanalyse fane"""
        st.markdown("#### Komponentanalyse af Love- og Rayleigh-bølger")
        
        # Hent Love ankomst tid
        love_arrival = station.get('love_arrival', 300)
        
        # Definer standard værdier
        default_start = float(love_arrival - 30)
        default_duration = 300.0
        
        # Initialiser session state værdier hvis ikke sat
        if 'wave_motion_start' not in st.session_state:
            st.session_state.wave_motion_start = default_start
            st.session_state.wave_motion_duration = default_duration
            st.session_state.wave_first_load = True
        
        # Kontrolpanel
        col1, col2 = st.columns([1,7])
        with col1:
            motion_start = st.number_input(
                "Analyse start tid (s)",
                min_value=0.0,
                max_value=3600.0,
                value=st.session_state.wave_motion_start,
                step=10.0,
                key="wave_start_input"
            )
            motion_duration = st.number_input(
                "Analyse varighed (s)",
                min_value=10.0,
                max_value=600.0,
                value=st.session_state.wave_motion_duration,
                step=10.0,
                key="wave_duration_input"
            )
            
            # DEFINER motion_window HER - INDEN KNAPPEN!
            motion_window = (motion_start, motion_start + motion_duration)
            
            # Manuel genberegning knap
            st.markdown("""
            <style>
                /* Style update button to match number inputs */
                div[data-testid="stButton"] button[kind="secondary"] {
                    background-color: #f0f2f6;
                    border: 1px solid #d0d2d6;
                    height: 38px !important;
                    border-radius: 0.25rem;
                    padding: 0.25rem 1rem;
                    font-size: 14px;
                    font-weight: 400;
                    color: #262730;
                    width: 100%;
                    transition: all 0.2s;
                    margin: 0;
                }
                
                div[data-testid="stButton"] button[kind="secondary"]:hover {
                    background-color: #e0e2e6;
                    border-color: #b0b2b6;
                }
            </style>
            """, unsafe_allow_html=True)

            # Knappen
            if st.button("↻ Opdater", key="update_styled", use_container_width=True, type="secondary"):
                with st.spinner("Analyserer bevægelsesmønstre..."):
                    wave_analysis = self.processor.detect_wave_types(
                        st.session_state.get('display_data', waveform_data),
                        motion_window
                    )
                    
                    if 'error' not in wave_analysis:
                        st.session_state.wave_analysis = wave_analysis
                        st.success("Analyse opdateret!")
                        st.rerun()
                    else:
                        st.error(f"Fejl i analyse: {wave_analysis['error']}")
        
        with col2:
            # AUTOMATISK TIDSSERIE PLOT
            fig_timeseries = go.Figure()
            
            # Hent tidsdata og displacement data
            time_array = waveform_data.get('time_seconds', waveform_data.get('time', []))
            displacement_data = waveform_data.get('displacement_data', {})
            
            if len(time_array) > 0:
                # Find start index baseret på Love ankomst
                start_idx = np.argmin(np.abs(np.array(time_array) - love_arrival))
                
                # Plot hver komponent fra Love ankomst
                components = [
                    ('vertical', 'Z (Vertikal)', 'blue'),
                    ('north', 'N (Nord-Syd)', 'red'),
                    ('east', 'E (Øst-Vest)', 'green')
                ]
                
                for comp_key, comp_name, color in components:
                    if comp_key in displacement_data and displacement_data[comp_key] is not None:
                        data = np.asarray(displacement_data[comp_key]).flatten()
                        # Plot fra Love ankomst og fremad
                        fig_timeseries.add_trace(go.Scatter(
                            x=time_array[start_idx:],
                            y=data[start_idx:],
                            mode='lines',
                            name=comp_name,
                            line=dict(color=color, width=1.5)
                        ))
                
                # Tilføj markører
                if station.get('love_arrival'):
                    fig_timeseries.add_vline(
                        x=station['love_arrival'],
                        line_dash="dot",
                        line_color="purple",
                        annotation_text="Love"
                    )
                
                if station.get('rayleigh_arrival'):
                    fig_timeseries.add_vline(
                        x=station['rayleigh_arrival'],
                        line_dash="dot",
                        line_color="darkgreen",
                        annotation_text="Rayleigh"
                    )
                
                # Marker analysevindue - brug direkte værdier
                fig_timeseries.add_vrect(
                    x0=motion_start,
                    x1=motion_start + motion_duration,
                    fillcolor="yellow",
                    opacity=0.2,
                    layer="below",
                    line_width=0,
                    annotation_text="Analysevindue",
                    annotation_position="top"
                )
                
                # Layout
                fig_timeseries.update_layout(
                    title="Overfladebølger - Tidsserie fra Love-bølge ankomst",
                    xaxis_title="Tid (sekunder efter jordskælv)",
                    yaxis_title="Amplitude (nm)",
                    height=400,
                    hovermode='x unified',
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1
                    )
                )
                
                # Vis tidsserie plot
                st.plotly_chart(fig_timeseries, use_container_width=True)
        
        # Opdater session state
        st.session_state.wave_motion_start = motion_start
        st.session_state.wave_motion_duration = motion_duration
        motion_window = (motion_start, motion_start + motion_duration)
        
        # AUTOMATISK ANALYSE VED FØRSTE LOAD
        if st.session_state.get('wave_first_load', False):
            with st.spinner("Kører initial analyse..."):
                wave_analysis = self.processor.detect_wave_types(
                    st.session_state.get('display_data', waveform_data),
                    motion_window
                )
                if 'error' not in wave_analysis:
                    st.session_state.wave_analysis = wave_analysis
                    st.session_state.wave_first_load = False
        
        # Vis eksisterende resultater hvis de findes
        if 'wave_analysis' in st.session_state:
            wave_analysis = st.session_state.wave_analysis
            
            
            
            # vis particle motion plot
            
            
            motion_fig = self.visualizer.create_particle_motion_plot(
                st.session_state.get('display_data', waveform_data),
                time_window=motion_window
            )
            
            if motion_fig:
                st.plotly_chart(motion_fig, use_container_width=True)
            
            # Vis resultater 
        
            col1, col2, col3 = st.columns(3)

            with col1:
                st.markdown("**Dominerende type**")
                st.markdown(f"### {wave_analysis['dominant_type']}")
                st.caption(f"{wave_analysis['confidence']:.0%} sikkerhed")

            with col2:
                st.markdown("**Love/Rayleigh ratio**")
                st.markdown(f"### {wave_analysis['love_rayleigh_ratio']:.1f}")

            with col3:
                h_ratio = wave_analysis['horizontal_ratio']
                v_ratio = wave_analysis['vertical_ratio']
                st.markdown("**Energi fordeling**")
                st.markdown(f"H: {h_ratio:.0%} | V: {v_ratio:.0%}")
            
            # Fortolkning
            st.info(f"💡 {wave_analysis['interpretation']}")
            
            # Forklaring af particle motion
            with st.expander("Sådan tolkes particle motion"):
                st.markdown("""
                **Particle motion** viser hvordan jorden bevæger sig i 3D under bølgens passage:
                
                - **Love bølger**: Viser lineær bevægelse i N-E plot (horisontal)
                - **Rayleigh bølger**: Viser elliptisk bevægelse i Z-N og Z-E plots (retrograd)
                - **Blandet signal**: Viser kompleks bevægelse i alle planer
                
                Jo mere lineær bevægelsen er i det horisontale plan, desto mere Love-bølge domineret er signalet.
                """)
        
        else:
            # Ingen analyse endnu
            st.info("Klik 'Genberegn analyse' for at starte bølgetype analyse")
        
        
          
            
    def _calculate_ms_magnitude(self, waveform_data, station, eq, reference_period, 
                            window_start, window_duration, apply_filter, sampling_rate):
        """Beregn Ms magnitude"""
        with st.spinner("Beregner..."):
            try:
                # Gem parametre
                st.session_state.ms_reference_period = reference_period
                
                # Hent data
                data_source = waveform_data.get('displacement_data', {})
                
                # Hent komponenter
                north_data = np.array(data_source.get('north', []))
                east_data = np.array(data_source.get('east', []))
                vertical_data = np.array(data_source.get('vertical', []))
                
                # Ekstraher vindue
                start_idx = int(window_start * sampling_rate)
                end_idx = int((window_start + window_duration) * sampling_rate)
                
                # Begræns til data længde
                start_idx = max(0, start_idx)
                end_idx = min(end_idx, len(north_data), len(east_data), len(vertical_data))
                
                # Udtræk vindue
                north_window = north_data[start_idx:end_idx] if len(north_data) > start_idx else np.array([])
                east_window = east_data[start_idx:end_idx] if len(east_data) > start_idx else np.array([])
                vertical_window = vertical_data[start_idx:end_idx] if len(vertical_data) > start_idx else np.array([])
                
                # Beregn Ms
                ms_result, explanation = self.processor.calculate_ms_magnitude(
                    north_window,
                    east_window,
                    vertical_window,
                    station.get('distance_km', 0),
                    sampling_rate,
                    period=reference_period,
                    earthquake_depth_km=eq.get('depth', 0),
                    apply_filter=apply_filter
                )
                
                # Gem resultater
                st.session_state.ms_result = ms_result
                st.session_state.ms_explanation = explanation
                st.session_state.ms_window = {
                    'start': window_start,
                    'duration': window_duration,
                    'start_idx': start_idx,
                    'end_idx': end_idx
                }
                st.session_state.ms_filter_applied = apply_filter
                
                #st.success(f"Ms = {ms_result:.1f}")
                
            except Exception as e:
                st.error(f"Fejl: {str(e)}")


    def _render_fft_analysis_unified(self, waveform_data, sampling_rate, window_start, window_duration):
        """FFT analyse for Ms vindue"""
        try:
            data_source = waveform_data.get('displacement_data', {})
            time_array = waveform_data.get('time', [])
            
            # Vindue indekser
            start_idx = int(window_start * sampling_rate)
            end_idx = int((window_start + window_duration) * sampling_rate)
            
            # Toggle for visning
            show_individual = st.checkbox("Vis individuelle komponenter", value=False, key="fft_toggle")
            
            # Plot
            fig = go.Figure()
            
            if show_individual:
                # Plot hver komponent
                colors = {'vertical': 'blue', 'north': 'red', 'east': 'green'}
                
                for comp_name, color in colors.items():
                    if comp_name in data_source:
                        comp_data = data_source[comp_name]
                        if start_idx < len(comp_data) and end_idx <= len(comp_data):
                            windowed_data = comp_data[start_idx:end_idx]
                            
                            # FFT
                            N = len(windowed_data)
                            yf = fft(windowed_data - np.mean(windowed_data))
                            xf = fftfreq(N, 1/sampling_rate)[:N//2]
                            power = 2.0/N * np.abs(yf[:N//2])
                            
                            # Til perioder
                            valid_mask = xf > 0
                            periods = 1.0 / xf[valid_mask]
                            
                            fig.add_trace(go.Scatter(
                                x=periods,
                                y=power[valid_mask],
                                mode='lines',
                                name=comp_name.capitalize(),
                                line=dict(color=color, width=1.5)
                            ))
            else:
                # Samlet energi
                total_energy = None
                valid_periods = None
                
                for comp_name in ['north', 'east', 'vertical']:
                    if comp_name in data_source:
                        comp_data = data_source[comp_name]
                        if start_idx < len(comp_data) and end_idx <= len(comp_data):
                            windowed_data = comp_data[start_idx:end_idx]
                            
                            # FFT
                            N = len(windowed_data)
                            yf = fft(windowed_data - np.mean(windowed_data))
                            xf = fftfreq(N, 1/sampling_rate)[:N//2]
                            power = np.abs(yf[:N//2])**2
                            
                            valid_mask = xf > 0
                            periods = 1.0 / xf[valid_mask]
                            
                            if total_energy is None:
                                total_energy = power[valid_mask]
                                valid_periods = periods
                            else:
                                min_len = min(len(total_energy), len(power[valid_mask]))
                                total_energy[:min_len] += power[valid_mask][:min_len]
                
                if total_energy is not None:
                    total_amplitude = np.sqrt(total_energy / 3)
                    
                    fig.add_trace(go.Scatter(
                        x=valid_periods,
                        y=total_amplitude,
                        mode='lines',
                        name='Samlet energi',
                        line=dict(color='#6610f2', width=2),
                        fill='tozeroy',
                        fillcolor='rgba(102, 16, 242, 0.1)'
                    ))
            
            # Marker reference periode
            fig.add_vline(
                x=st.session_state.get('ms_reference_period', 20),
                line_dash="dash",
                line_color="red",
                annotation_text=f"T = {st.session_state.get('ms_reference_period', 20)}s"
            )
            
            # Layout
            all_y = []
            for trace in fig.data:
                if hasattr(trace, 'y') and trace.y is not None:
                    all_y.extend(trace.y)
            
            y_max = max(all_y) * 1.2 if all_y else 1
            
            fig.update_layout(
                xaxis_title="Periode (sekunder)",
                yaxis_title="Amplitude" if show_individual else "Energi",
                height=350,
                xaxis=dict(
                    range=[5, 35],
                    tickmode='linear',
                    tick0=5,
                    dtick=5
                ),
                yaxis=dict(range=[0, y_max]),
                showlegend=show_individual,
                margin=dict(t=20, b=40)
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
        except Exception as e:
            st.error(f"FFT fejl: {str(e)}")


    def _render_ms_calculation_details(self, explanation, station, eq):
        """Vis detaljeret gennemgang af Ms beregning med faktiske værdier"""
        
        # Advarsler først
        distance_km = station.get('distance_km', 0)
        eq_depth = eq.get('depth', 0)
        
        if distance_km < 2000 or distance_km > 16000 or eq_depth > 60:
            st.warning("### ⚠️ Valideringsadvarsler")
            
            if distance_km < 2000:
                st.markdown(f"""
                **Kort afstand: {distance_km:.0f} km < 2000 km**
                - Rayleigh-bølger ikke fuldt udviklede
                - Korrektion anvendt: +{explanation.get('distance_correction', {}).get('correction', 0):.3f}
                """)
            
            if distance_km > 16000:
                st.markdown(f"""
                **Lang afstand: {distance_km:.0f} km > 16000 km (160°)**
                - Ms upålidelig ved meget store afstande
                - Overvej alternativ magnitude skala
                """)
            
            if eq_depth > 60:
                st.markdown(f"""
                **Dybt jordskælv: {eq_depth:.0f} km > 60 km**
                - Svagere overfladebølger
                - Korrektion anvendt: {explanation.get('depth_correction', {}).get('correction', 0):.3f}
                """)
        
        # Beregningsgennemgang
        st.markdown("### 📊 Din Ms Beregning - Step by Step")
        
        # Step 1: Input værdier
        with st.expander("Step 1: Målte værdier", expanded=True):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.markdown("**Amplitude**")
                amp = explanation['amplitudes']
                st.write(f"Nord: {amp['north']:.1f} μm")
                st.write(f"Øst: {amp['east']:.1f} μm")
                st.write(f"Vertikal: {amp['vertical']:.1f} μm")
                st.write(f"Horisontal: {amp['horizontal']:.1f} μm")
                st.success(f"Brugt: {amp['used']:.1f} μm ({explanation['used_component']})")
            
            with col2:
                st.markdown("**Parametre**")
                params = explanation['parameters']
                st.write(f"Periode: {params['period']:.1f} s")
                st.write(f"Afstand: {params['distance_km']:.0f} km")
                st.write(f"Afstand: {params['distance_deg']:.2f}°")
                st.write(f"Sampling: {params['sampling_rate']:.0f} Hz")
            
            with col3:
                st.markdown("**Filter**")
                filt = explanation['filter']
                if filt['applied']:
                    st.write(f"Type: Båndpas")
                    st.write(f"Lavpas: {filt['low_freq']:.3f} Hz")
                    st.write(f"Højpas: {filt['high_freq']:.3f} Hz")
                else:
                    st.write("Ingen filtrering")
        
        # Step 2: Beregning
        with st.expander("Step 2: IASPEI formel anvendelse"):
            calc = explanation['calculation']
            
            st.latex(r"Ms = \log_{10}\left(\frac{A}{T}\right) + 1.66 \times \log_{10}(\Delta) + 3.3")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Mellemregninger:**")
                st.write(f"A/T = {calc['amplitude_period_ratio']:.2f}")
                st.write(f"log₁₀(A/T) = {calc['log_amp_period']:.4f}")
                st.write(f"log₁₀(Δ) = {calc['log_distance']:.4f}")
                st.write(f"1.66 × log₁₀(Δ) = {calc['distance_term']:.4f}")
            
            with col2:
                st.markdown("**Samlet:**")
                st.write(f"{calc['log_amp_period']:.4f} + {calc['distance_term']:.4f} + 3.3")
                st.write(f"= {calc['raw_result']:.2f}")
        
        # Step 3: Korrektioner
        if explanation.get('distance_correction', {}).get('applied') or explanation.get('depth_correction', {}).get('applied'):
            with st.expander("Step 3: Korrektioner"):
                if explanation.get('distance_correction', {}).get('applied'):
                    st.markdown("**Afstandskorrektion**")
                    dc = explanation['distance_correction']
                    st.write(f"Afstand: {dc['distance_km']:.0f} km < 2000 km")
                    st.write(f"Faktor: {dc['factor']:.3f}")
                    st.write(f"Korrektion: +{dc['correction']:.3f}")
                
                if explanation.get('depth_correction', {}).get('applied'):
                    st.markdown("**Dybdekorrektion**")
                    dp = explanation['depth_correction']
                    st.write(f"Dybde: {dp['depth_km']:.0f} km > 50 km")
                    st.write(f"Korrektion: {dp['correction']:.3f}")
        
        # Final resultat
        st.markdown("### 🎯 Endeligt Resultat")
        st.success(f"**Ms = {explanation['magnitude']:.1f}**")


#-SLUT ANALYSESIDE
    def render_data_export_view(self):
        """Render export tools view - med fungerende export"""
        # Vis breadcrumb navigation
        self.render_breadcrumb_with_title("Data Eksport")
        
        # Check om vi har data at eksportere
        if ('waveform_data' not in st.session_state or 
            'selected_earthquake' not in st.session_state or
            'selected_station' not in st.session_state):
            st.warning("📊 Ingen data at eksportere. Download først data fra Seismogram siden.")
            return
        
        # Hent data
        waveform_data = st.session_state.waveform_data
        selected_eq = st.session_state.selected_earthquake
        selected_station = st.session_state.selected_station
        
        # Check for høj-opløsnings data
        has_highres = False
        highres_rates = {}
        if 'original_data' in waveform_data and 'displacement' in waveform_data['original_data']:
            has_highres = True
            for comp, data in waveform_data['original_data']['displacement'].items():
                if isinstance(data, dict) and 'sampling_rate' in data:
                    highres_rates[comp] = data['sampling_rate']
        
        # HOVED LAYOUT - 2 kolonner
        col_left, col_right = st.columns([3, 2])
        
        # VENSTRE KOLONNE - Data valg og info
        with col_left:
            # Station info
        
            st.markdown(f"""
            <div style='background-color: #f8f9fa; padding: 12px; border-radius: 8px; margin-bottom: 16px;'>
                <strong>Jordskælv:</strong> M{selected_eq['magnitude']:.1f} - {selected_eq.get('location', 'Unknown')}<br>
                <strong>Station:</strong> {selected_station['network']}.{selected_station['station']} ({selected_station['distance_km']:.0f} km)<br>
                <strong>Dato:</strong> {selected_eq['time'].split('T')[0]}
            </div>
            """, unsafe_allow_html=True)
            
            
            
            # Data valg sektion
            st.markdown("### Vælg data til eksport")
            
            # Container med border
            with st.container():
                
                # Grunddata sektion
                st.markdown("##### Grunddata")
                
                col1, col2 = st.columns(2)
                with col1:
                    export_raw = st.checkbox(
                        "**Rådata** (counts)", 
                        value=False,
                        help="Direkte fra instrument - ikke kalibreret"
                    )
                with col2:
                    export_unfiltered = st.checkbox(
                        "**Displacement** (mm)", 
                        value=True,
                        help="Kalibreret jordbevægelse i millimeter"
                    )
                
                
                
                # Filtrerede data sektion
                st.markdown("##### Filtrerede data - båndpassfilter")
                
                col1, col2 = st.columns(2)
                with col1:
                    export_broadband = st.checkbox(
                        "**Bredbånd**", 
                        value=False,
                        help="0.01-25 Hz - Generel visning"
                    )
                with col2:
                    export_surface = st.checkbox(
                        "**Overfladebølger**", 
                        value=False,
                        help="0.02-0.5 Hz - Til Ms beregning"
                    )
                
                col1, col2 = st.columns(2)
                with col1:
                    export_p = st.checkbox(
                        "**P-bølger**", 
                        value=False,
                        help="1-10 Hz - Første ankomster"
                    )
                with col2:
                    export_s = st.checkbox(
                        "**S-bølger**", 
                        value=False,
                        help="0.5-5 Hz - Sekundære ankomster"
                    )
            
            
                
            
            # Datakvalitet indikator
            if has_highres:
                st.success(f"✅ Høj-opløsnings data tilgængeligt ({', '.join([f'{k}: {v}Hz' for k,v in highres_rates.items()])})")
        
        # HØJRE KOLONNE - Indstillinger og download
        with col_right:
            
            
            st.markdown("### ⚙️ Indstillinger")
            
            # Sampling indstillinger
            with st.container():
                
                
                sample_option = st.selectbox(
                    "Opløsning:",
                    ["Lav (3600 punkter)", 
                    "Standard (7200 punkter)", 
                    "Høj (14400 punkter)", 
                    "Fuld opløsning"],
                    index=1,
                    help="Flere punkter = større fil, bedre detaljer"
                )
                
                # Parse valg
                if "3600" in sample_option:
                    max_samples = 3600
                elif "7200" in sample_option:
                    max_samples = 7200
                elif "14400" in sample_option:
                    max_samples = 14400
                else:
                    max_samples = None
                
                # Vis estimeret filstørrelse
                n_components = 3
                n_selected = sum([export_raw, export_unfiltered, export_broadband, 
                                export_surface, export_p, export_s])
                
                if n_selected > 0:
                    if max_samples:
                        total_points = max_samples * n_components * n_selected
                        size_mb = (total_points * 20) / (1024 * 1024)
                        st.markdown(f"""
                        <div style='background-color: #e8f4fd; padding: 10px; border-radius: 5px; margin: 10px 0;'>
                            <strong>Estimeret størrelse:</strong> ~{size_mb:.1f} MB
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style='background-color: #fff3cd; padding: 10px; border-radius: 5px; margin: 10px 0;'>
                            <strong>Estimeret størrelse:</strong> Stor fil (fuld opløsning)
                        </div>
                        """, unsafe_allow_html=True)
                
                # Excel format info
                
            
            
            # DOWNLOAD SEKTION
            # Sammensæt export options - VIGTIGT!
            export_options = {
                'raw_data': export_raw,
                'unfiltered': export_unfiltered,
                'broadband': export_broadband,
                'surface': export_surface,
                'p_waves': export_p,
                's_waves': export_s,
                'max_samples': max_samples
            }
            
            # Check om MINDST ÉN er valgt
            any_selected = any([export_raw, export_unfiltered, export_broadband, 
                            export_surface, export_p, export_s])
            
            if any_selected:
                # Download sektion
                
                
                try:
                    # Forbered data
                    with st.spinner("Forbereder data..."):
                        # Hent managers
                        data_manager = get_cached_data_manager()
                        processor = get_cached_seismic_processor()
                        
                        # Kopier waveform data
                        export_waveform = waveform_data.copy()
                        
                        # Process filtre hvis nødvendigt
                        if any([export_broadband, export_surface, export_p, export_s]):
                            export_waveform['filtered_datasets'] = {}
                            
                            filter_map = {
                                'broadband': export_broadband,
                                'surface': export_surface,
                                'p_waves': export_p,
                                's_waves': export_s
                            }
                            
                            for filter_key, is_selected in filter_map.items():
                                if is_selected:
                                    try:
                                        filtered = processor.process_waveform_with_filtering(
                                            export_waveform,
                                            filter_type=filter_key,
                                            remove_spikes=True,
                                            calculate_noise=False
                                        )
                                        
                                        if filtered and 'filtered_data' in filtered:
                                            export_waveform['filtered_datasets'][filter_key] = filtered['filtered_data']
                                    except Exception as e:
                                        st.warning(f"Kunne ikke processere {filter_key} filter")
                        
                        # Generer Excel
                        excel_data = data_manager.export_to_excel(
                            earthquake=selected_eq,
                            station=selected_station,
                            waveform_data=export_waveform,
                            ms_magnitude=st.session_state.get('ms_result'),
                            ms_explanation=st.session_state.get('ms_explanation', ''),
                            export_options=export_options
                        )
                    
                    if excel_data:
                        # Generer filnavn
                        eq_date = selected_eq['time'].split('T')[0].replace('-', '')
                        filename = f"GEOseis_{selected_station['network']}_{selected_station['station']}_{eq_date}_M{selected_eq['magnitude']:.1f}.xlsx"
                        
                        # Download info
                        dataset_count = sum([export_raw, export_unfiltered, export_broadband, 
                                        export_surface, export_p, export_s])
                        points_info = f"{max_samples} punkter" if max_samples else "Fuld opløsning"
                        
                        st.markdown("📥 Klar til download")
                        
                        # Custom CSS for lyseblå download knap
                        st.markdown("""
                        <style>
                        div[data-testid="stDownloadButton"] > button {
                            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%);
                            color: #0056B3;
                            border: 1.5px solid #5DADE2;
                            padding: 0.75rem 1.5rem;
                            font-size: 1rem;
                            font-weight: 600;
                            border-radius: 0.5rem;
                            width: 100%;
                            transition: all 0.3s ease;
                            box-shadow: 0 0 0 2px rgba(93, 173, 226, 0.1);
                        }

                        div[data-testid="stDownloadButton"] > button:hover {
                            background: linear-gradient(135deg, #D6EBFD 0%, #B8DAFF 100%);
                            border-color: #3498DB;
                            transform: translateY(-2px);
                            box-shadow: 0 4px 8px rgba(93, 173, 226, 0.2);
                        }
                        </style>
                        """, unsafe_allow_html=True)
                        
                        # Download knap
                        st.download_button(
                            label="Download Excel fil",
                            data=excel_data,
                            file_name=filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                        
                        with st.expander("📄 Se detaljer om metadata ", expanded=False):
                            st.markdown("""
                            **Ark i filen:**
                            - Metadata (jordskælv & station info)
                            - Time_Series_Data (alle valgte datasæt)
                            - Ms_Calculation (hvis beregnet)
                            
                            **Tidsformat:** Sekunder fra jordskælv (0 = jordskælvstid)
                            """)    
                    else:
                        st.error("❌ Kunne ikke generere Excel fil")
                
                except Exception as e:
                    st.error(f"❌ Export fejl: {str(e)}")
                    with st.expander("Se fejldetaljer"):
                        import traceback
                        st.code(traceback.format_exc())
                
                st.markdown("</div>", unsafe_allow_html=True)
            else:
                # Ingen data valgt
                st.markdown("""
                <div style='background-color: #fff3cd; padding: 1rem; border-radius: 0.5rem; text-align: center;'>
                    <div style='font-size: 1.5rem; margin-bottom: 0.5rem;'>⚠️</div>
                    <div style='color: #856404; font-weight: 500;'>Vælg mindst ét datasæt</div>
                </div>
                """, unsafe_allow_html=True)

    def render_theory_guide_view(self):
        """Render teori og metoder vejledning - målrettet gymnasielærere"""
        st.markdown("## Teori & Metoder")
        
        # Navigation tabs
        tab1, tab2, tab3, tab4, tab5,tab6 = st.tabs([
            "Seismiske bølger", 
            "Stationsudvælgelse", 
            "Filtrering", 
            "Ms Magnitude", 
            "Kvalitetskontrol",
            "Tips til undervisningsbrug"
        ])
        
        with tab1:
            st.markdown("### Seismiske bølgetyper")
            st.markdown("""
            #### De fire hovedtyper
            
            Når et jordskælv opstår, udsendes energi som seismiske bølger. 
            I GEOseis arbejder vi med fire typer:
            
            **1. P-bølger (Primære bølger)**
            - Kompressionsbølger (som lydbølger)
            - Hurtigste type: 6-8 km/s i skorpen
            - Ankommer først til seismografen
            - Bevægelse: frem og tilbage i udbredelsesretningen
            
            **2. S-bølger (Sekundære bølger)**  
            - Forskydningsbølger
            - Hastighed: 3.5-4.5 km/s (ca. 58% af P-bølge hastighed)
            - Ankommer efter P-bølgen
            - Bevægelse: op/ned og side til side (vinkelret på udbredelsen)
            - Kan ikke udbredes i væsker
            
            **3. Love-bølger**
            - Overfladebølge med horisontal bevægelse
            - Hastighed: ca. 92% af S-bølge hastighed
            - Største amplitude på horisontale komponenter (N, Ø)
            - Vigtig for skader på bygninger (horisontal rystelse)
            
            **4. Rayleigh-bølger**
            - Overfladebølge med elliptisk bevægelse
            - Hastighed: ca. 90% af S-bølge hastighed
            - Synlig på alle komponenter, især vertikal
            - Føles som "rullen" under jordskælv
            """)
            
            # Hastighedsberegninger
            st.markdown("#### Hastighedsberegninger i GEOseis")
            st.info("""
            **Intelligent hastighedsberegning:**
            
            GEOseis bruger TauP-modellen (iasp91) til at beregne P og S ankomsttider 
            baseret på Jordens 3D hastighedsstruktur.
            """)
            self.render_surface_wave_theory()
            
            
        
        with tab2:
            st.markdown("### Automatisk stationsudvælgelse")
            
            st.markdown("""
            GEOseis finder automatisk de bedste seismiske stationer til analyse. 
            Her er hvordan systemet fungerer:
            
            #### 1. Geografisk søgning
            - Søger i en ring omkring jordskælvet (typisk 500-3000 km)
            - Bruger IRIS database med over 1000 stationer globalt
            - Finder typisk 50-500 kandidater
            
            #### 2. Prioritering efter kvalitet
            Stationer rangeres efter:
            
            **Netværk prioritet:**
            - 🥇 **IU, II**: Global Seismographic Network (højeste kvalitet)
            - 🥈 **G, GE**: GEOSCOPE/GEOFON (meget god kvalitet)
            - 🥉 **Andre**: Regionale netværk (varierende kvalitet)
            
            **Kanal prioritet:**
            - **HH**: High-gain, High sample rate (100 Hz) - bedst
            - **BH**: Broadband, High-gain (20-40 Hz) - god
            - **Andre**: Varierende kvalitet
            
            #### 3. Geografisk fordeling
            Systemet vælger stationer med god spredning:
            - Undgår klynger af stationer samme sted
            - Sikrer azimuthal dækning omkring jordskælvet
            - Optimerer for forskellige afstande
            
            #### 4. Datatilgængelighed
            For hver kandidat tjekkes:
            - Om stationen var aktiv på jordskælvstidspunktet
            - Om data faktisk er tilgængelig i IRIS
            - Om alle tre komponenter (N, Ø, Z) fungerer
            
            #### 5. Smart validering
            - **Få stationer (<20)**: Alle valideres grundigt
            - **Mange stationer (>20)**: Kun top kandidater valideres
            - Sparer tid uden at gå på kompromis med kvalitet
            """)
            
            # Eksempel
            with st.expander("💡 Eksempel på stationsudvælgelse"):
                st.markdown("""
                **Jordskælv:** M 7.2 i Japan, 50 km dybde
                
                1. **Søgning:** 1000-5000 km radius → 347 stationer fundet
                2. **Filtrering:** Kun HH/BH kanaler → 198 stationer
                3. **Prioritering:** GSN netværk først → Top 50 udvalgt
                4. **Fordeling:** 10 afstandsintervaller → 1-2 fra hver
                5. **Validering:** Test datatilgængelighed → 8 verificeret
                6. **Resultat:** 3 bedste stationer valgt automatisk
                
                Hele processen tager typisk 5-15 sekunder.
                """)
        
        with tab3:
            st.markdown("### Signalfiltrering")
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("""
                #### Hvorfor filtrere?
                
                Seismiske signaler indeholder mange frekvenser. Forskellige bølgetyper 
                dominerer ved forskellige frekvenser:
                
                - **Højfrekvens (>1 Hz)**: P og S bølger
                - **Mellemfrekvens (0.1-1 Hz)**: Blanding af alle typer
                - **Lavfrekvens (<0.1 Hz)**: Overfladebølger
                
                Ved at filtrere kan vi:
                - Fremhæve specifikke bølgetyper
                - Fjerne støj (f.eks. vind, trafik)
                - Forbedre signal-til-støj forhold
                """)
                
                st.markdown("#### Butterworth filter")
                st.info("""
                GEOseis bruger **Butterworth båndpasfiltre**:
                
                - Flad frekvensrespons i pasbåndet
                - Ingen "ripples" som kan forvrænge signalet
                - 4. ordens filter (god balance mellem skarphed og stabilitet)
                - Zero-phase filtering (ingen tidsforsinkelse)
                """)
            
            with col2:
                st.markdown("#### Prædefinerede filtre")
                
                filter_df = pd.DataFrame({
                    "Filter": ["Bredbånd", "P-bølger", "S-bølger", "Overfladebølger"],
                    "Frekvens": ["0.01-25 Hz", "1-10 Hz", "0.5-5 Hz", "0.02-0.5 Hz"],
                    "Periode": ["0.04-100 s", "0.1-1 s", "0.2-2 s", "2-50 s"],
                    "Anvendelse": [
                        "Se alt, ingen filtrering",
                        "Tydelige P ankomster",
                        "S-bølge analyse", 
                        "Ms magnitude beregning"
                    ]
                })
                st.dataframe(filter_df, hide_index=True, use_container_width=True)
                
                st.markdown("#### Brugerdefineret filter")
                st.markdown("""
                Du kan også definere egne filtre:
                
                **Tips:**
                - Start bredt (f.eks. 0.1-10 Hz)
                - Indsnævre gradvist
                - Husk Nyquist grænsen: max = sampling rate / 2
                - For 100 Hz data: max ~45 Hz praktisk
                """)
            
            # Eksempel på filtrering
            with st.expander("💡 Eksempel: Effekt af filtrering"):
                st.markdown("""
                **Scenarie:** M 6.5 jordskælv, 2000 km afstand
                
                **Uden filter:**
                - Alle bølgetyper blandet sammen
                - Svært at identificere P og S ankomster
                - Overfladebølger dominerer sent i signalet
                
                **Med P-bølge filter (1-10 Hz):**
                - Tydelig P ankomst ved ~250 sekunder
                - S-bølge også synlig
                - Overfladebølger næsten væk
                
                **Med overfladebølge filter (0.02-0.5 Hz):**
                - P og S bølger forsvinder
                - Store overfladebølger efter ~500 sekunder
                - Perfekt til Ms magnitude måling
                """)
        
        with tab4:
            st.markdown("#### Ms Magnitude beregning")
            
            st.markdown("""
            #### Hvad er Ms?
            
            **Ms** (surface wave magnitude) er en magnitudeskala baseret på 
            overfladebølgernes amplitude. Den er særligt velegnet til:
            
            - Jordskælv mellem M 5.0 og 8.0
            - Afstande mellem 2° og 160° (200-16,000 km)
            - Overfladiske jordskælv (< 60 km dybde)
            
            #### IASPEI 2013 formel
            """)
            
            st.latex(r"Ms = \log_{10}\left(\frac{A}{T}\right) + 1.66 \times \log_{10}(\Delta) + 3.3")
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("""
                **Hvor:**
                - **A**: Maksimum amplitude (μm)
                - **T**: Bølgeperiode (standard: 20 s)
                - **Δ**: Afstand i grader
                - **1.66**: Geometrisk spredning
                - **3.3**: Kalibreringskonstant
                """)
            
            with col2:
                st.markdown("""
                **Vigtige detaljer:**
                - Måles på Rayleigh bølger
                - Typisk 5-20 min efter P-bølgen
                - Største vertikal eller horisontal amplitude
                - Filtreres til 0.02-0.5 Hz (2-50 s periode)
                """)
            
            # Korrektioner
            st.markdown("#### Korrektioner i GEOseis")
            
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("""
                **Afstandskorrektion (< 2000 km):**
                
                Ved korte afstande er Rayleigh-bølgerne ikke fuldt udviklede, 
                hvilket giver for lave amplituder.
                
                - Korrektion = +0.3 × (2000 - afstand) / 2000
                - Maksimalt +0.3 magnitude enheder
                - Kompenserer for udviklingsdistance
                """)
            
            with col2:
                st.markdown("""
                **Dybdekorrektion (> 50 km):**
                
                Dybe jordskælv genererer svagere overfladebølger pga. 
                energispredning i dybden.
                
                - Korrektion = +0.0035 × (dybde - 50)
                - Øger magnitude for dybe skælv
                - Vigtig for subduktionszoner
                """)
            
            # Fejlkilder
            with st.expander("⚠️ Typiske fejlkilder og løsninger"):
                st.markdown("""
                **Problem: For lav Ms værdi**
                - Tjek om overfladebølger er synlige
                - Prøv længere analysevindue
                - Verificer filter indstillinger
                
                **Problem: For høj Ms værdi**
                - Tjek for lokale forstærkninger
                - Se efter støj/spikes i vinduet
                - Sammenlign flere stationer
                
                **Problem: Ingen overfladebølger**
                - Dybt jordskælv? (> 100 km)
                - For kort afstand? (< 200 km)
                - Tjek om stationen virker
                """)
        
        with tab5:
            st.markdown("### Kvalitetskontrol")
            
            st.markdown("""
            GEOseis udfører automatisk flere kvalitetskontroller for at sikre 
            pålidelige resultater:
            
            #### 1. Timing validering
            - Sammenligner teoretiske og observerede P-ankomsttider
            - Advarer hvis forskellen > 10 sekunder eller 10%
            - Hjælper med at opdage forkerte data
            
            #### 2. Signal-til-støj forhold (SNR)
            - Måler signalstyrke vs. baggrundsstøj
            - Beregnes for hver komponent
            - Lavt SNR = upålidelige målinger
            
            #### 3. Komponent konsistens
            - Tjekker om alle tre komponenter (N, Ø, Z) er tilgængelige
            - Verificerer samme sampling rate
            - Advarer ved manglende komponenter
            
            #### 4. Ms magnitude validering
            Automatisk tjek for:
            - Afstand inden for gyldigt område (200-16,000 km)
            - Rimelig amplitude (ikke støj eller mætning)
            - Korrekt filteranvendelse
            - Sammenligning med officiel magnitude
            """)
            
            # Kvalitetsindikatorer
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("#### Gode kvalitetsindikatorer")
                st.success("""
                ✅ Alle tre komponenter tilgængelige  
                ✅ Høj sampling rate (≥40 Hz)  
                ✅ God SNR (>10)  
                ✅ Ms inden for 0.3 af officiel  
                ✅ Tydelige P, S og overfladebølger  
                """)
            
            with col2:
                st.markdown("#### Advarselstegn")
                st.warning("""
                ⚠️ Manglende komponenter  
                ⚠️ Lav sampling rate (<20 Hz)  
                ⚠️ Dårlig SNR (<3)  
                ⚠️ Ms afviger >0.5 fra officiel  
                ⚠️ Timing problemer  
                """)
            
        with tab6:
            # Tips til undervisning
            st.markdown("### Tips til undervisningsbrug")
            st.markdown("""
            **Øvelse 1: Sammenlign stationer**
            - Vælg samme jordskælv, forskellige stationer
            - Hvorfor varierer Ms lidt mellem stationer?
            - Diskuter fejlkilder og usikkerheder
            
            **Øvelse 2: Filter eksperimenter**
            - Start uden filter
            - Prøv forskellige filtre
            - Hvornår kan man se hver bølgetype bedst?
            
            **Øvelse 3: Kvalitetsvurdering**
            - Find eksempel med god kvalitet
            - Find eksempel med dårlig kvalitet
            - Hvad er forskellen?
            
            **Øvelse 4: Afstandsafhængighed**
            - Vælg stationer på forskellige afstande
            - Plot ankomsttider vs. afstand
            - Beregn tilsyneladende hastigheder
            """)    

    def render_surface_wave_theory(self):
        """
        Render teori sektion om overfladebølge hastigheder
        Kan tilføjes til theory_guide_view eller som selvstændig sektion
        """
        
        st.markdown("## 🌊 Overfladebølge Hastigheder")
        
        # Introduktion
        st.markdown("""
        Overfladebølger (Love og Rayleigh) rejser langs jordens overflade og har hastigheder 
        der afhænger af flere faktorer. I GEOseis bruger vi en avanceret model der tager højde 
        for disse faktorer for at give mere præcise ankomsttider.
        """)
        
        # Tabs for forskellige aspekter
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 Basis Hastigheder", 
            "🔧 Faktorer", 
            "📈 Beregningsmodel",
            "🧮 Live Beregner"
        ])
        
        with tab1:
            st.markdown("### Typiske Hastigheder")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### Love Bølger")
                st.markdown("""
                - **Typisk hastighed**: 3.8-5.2 km/s
                - **Gennemsnit**: 4.5 km/s
                - **Bevægelse**: Ren horisontal (SH)
                - **Polarisering**: Transversal
                """)
                
                # Visualisering af Love bølge
                fig_love = go.Figure()
                t = np.linspace(0, 4*np.pi, 100)
                fig_love.add_trace(go.Scatter(
                    x=t, 
                    y=np.sin(t),
                    mode='lines',
                    name='Love bølge',
                    line=dict(color='purple', width=3)
                ))
                fig_love.update_layout(
                    title="Love Bølge Bevægelse (Side til Side)",
                    xaxis_title="Afstand",
                    yaxis_title="Horisontal forskydning",
                    height=250,
                    showlegend=False
                )
                st.plotly_chart(fig_love, use_container_width=True)
            
            with col2:
                st.markdown("#### Rayleigh Bølger")
                st.markdown("""
                - **Typisk hastighed**: 3.0-4.5 km/s
                - **Gennemsnit**: 3.5 km/s
                - **Bevægelse**: Elliptisk retrograd
                - **Komponenter**: Vertikal + Radial
                """)
                
                # Visualisering af Rayleigh bølge
                fig_rayleigh = go.Figure()
                theta = np.linspace(0, 4*np.pi, 100)
                x = theta
                y = -0.6 * np.sin(theta)  # Vertikal
                z = np.cos(theta)          # Horisontal
                
                fig_rayleigh.add_trace(go.Scatter(
                    x=x,
                    y=y,
                    mode='lines',
                    name='Vertikal',
                    line=dict(color='blue', width=2)
                ))
                fig_rayleigh.add_trace(go.Scatter(
                    x=x,
                    y=z*0.4,
                    mode='lines', 
                    name='Horisontal',
                    line=dict(color='green', width=2, dash='dash')
                ))
                fig_rayleigh.update_layout(
                    title="Rayleigh Bølge (Elliptisk Bevægelse)",
                    xaxis_title="Afstand",
                    yaxis_title="Forskydning",
                    height=250,
                    showlegend=True
                )
                st.plotly_chart(fig_rayleigh, use_container_width=True)
            
            st.info("💡 **Hvorfor er Love hurtigere end Rayleigh?** Love bølger propagerer kun i de øvre lag, mens Rayleigh bølger involverer dybere strukturer med lavere hastigheder.")
        
        with tab2:
            st.markdown("### Faktorer der Påvirker Hastigheden")
            
            # 1. Dybde effekt
            st.markdown("#### 1. Jordskælvsdybde")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Graf over dybde effekt
                depths = np.array([10, 20, 35, 50, 70, 100, 150, 200, 300, 400])
                depth_factors = []
                for d in depths:
                    if d < 20:
                        factor = 1.0
                    elif d < 35:
                        factor = 0.98
                    elif d < 70:
                        factor = 0.92
                    elif d < 150:
                        factor = 0.80
                    elif d < 300:
                        factor = 0.65
                    else:
                        factor = 0.50
                    depth_factors.append(factor)
                
                fig_depth = go.Figure()
                fig_depth.add_trace(go.Scatter(
                    x=depths,
                    y=depth_factors,
                    mode='lines+markers',
                    name='Amplitude faktor',
                    line=dict(color='red', width=3),
                    marker=dict(size=8)
                ))
                fig_depth.update_layout(
                    title="Overfladebølge Amplitude vs Dybde",
                    xaxis_title="Jordskælvsdybde (km)",
                    yaxis_title="Relativ Amplitude",
                    height=300,
                    xaxis_type="log"
                )
                st.plotly_chart(fig_depth, use_container_width=True)
            
            with col2:
                st.markdown("""
                **Effekt på hastighed:**
                - < 20 km: Optimal (100%)
                - 20-70 km: Let reduceret
                - 70-150 km: Moderat reduceret
                - > 150 km: Stærkt reduceret
                
                Dybe jordskælv genererer svagere overfladebølger, hvilket også påvirker den dominerende periode.
                """)
            
            # 2. Afstands effekt
            st.markdown("#### 2. Afstand (Dispersion)")
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                distances = np.array([200, 500, 1000, 2000, 4000, 6000, 10000, 15000])
                dist_factors = []
                for d in distances:
                    if d < 500:
                        factor = 0.92
                    elif d < 1000:
                        factor = 0.95
                    elif d < 2000:
                        factor = 0.98
                    elif d < 4000:
                        factor = 1.0
                    elif d < 6000:
                        factor = 1.02
                    elif d < 10000:
                        factor = 1.04
                    else:
                        factor = 1.06
                    dist_factors.append(factor)
                
                fig_dist = go.Figure()
                fig_dist.add_trace(go.Scatter(
                    x=distances,
                    y=dist_factors,
                    mode='lines+markers',
                    name='Hastighedsfaktor',
                    line=dict(color='blue', width=3),
                    marker=dict(size=8)
                ))
                fig_dist.update_layout(
                    title="Gruppehastighed vs Afstand",
                    xaxis_title="Afstand (km)",
                    yaxis_title="Hastighedsfaktor",
                    height=300,
                    xaxis_type="log"
                )
                st.plotly_chart(fig_dist, use_container_width=True)
            
            with col2:
                st.markdown("""
                **Dispersion effekt:**
                - Kort afstand: Korte perioder dominerer (lavere hastighed)
                - Lang afstand: Lange perioder dominerer (højere hastighed)
                
                Dette skyldes at lange perioder "føler" dybere strukturer med højere hastigheder.
                """)
            
            # 3. Magnitude effekt
            st.markdown("#### 3. Magnitude")
            
            st.markdown("""
            Større jordskælv exciterer længere perioder, som rejser hurtigere:
            
            | Magnitude | Dominant Periode | Hastighedsfaktor |
            |-----------|-----------------|------------------|
            | < 5.0     | 5-10 s         | 0.95            |
            | 5.0-6.0   | 10-15 s        | 0.97-0.99       |
            | 6.0-7.0   | 15-25 s        | 1.00-1.02       |
            | 7.0-8.0   | 20-40 s        | 1.04-1.06       |
            | > 8.0     | > 40 s         | 1.08            |
            """)
            
            # 4. Skorpestruktur
            st.markdown("#### 4. Skorpestruktur (Vp/Vs ratio)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("""
                **Vp/Vs ratio indikerer skorpetype:**
                - **> 1.80**: Sedimentær (blødt materiale)
                - **1.75-1.80**: Normal kontinental skorpe
                - **1.70-1.75**: Gennemsnitlig
                - **< 1.70**: Krystallin skorpe (hårdt)
                """)
            
            with col2:
                st.info("""
                💡 **Beregning fra data:**
                
                Vp/Vs ≈ Ts/Tp
                
                Hvor Ts og Tp er S og P ankomsttider
                """)
        
        with tab3:
            st.markdown("### Samlet Beregningsmodel")
            
            st.markdown("""
            Den endelige hastighed beregnes som:
            
            **V = V₀ × f_depth × f_distance × f_magnitude × f_structure**
            
            Hvor:
            - **V₀**: Basis hastighed (4.5 km/s for Love, 3.5 km/s for Rayleigh)
            - **f_depth**: Dybdefaktor (0.5-1.0)
            - **f_distance**: Afstandsfaktor (0.92-1.06)
            - **f_magnitude**: Magnitudefaktor (0.95-1.08)
            - **f_structure**: Strukturfaktor (0.93-1.05)
            """)
            
            # Eksempel beregning
            with st.expander("📋 Eksempel Beregning", expanded=True):
                st.markdown("""
                **Jordskælv:** M 6.8, 45 km dyb, 2500 km væk
                
                **Love bølge:**
                - Basis: 4.5 km/s
                - Dybdefaktor: 0.92 (45 km dyb)
                - Afstandsfaktor: 0.99 (2500 km)
                - Magnitudefaktor: 1.02 (M 6.8)
                - Strukturfaktor: 1.0 (antaget normal)
                
                V_Love = 4.5 × 0.92 × 0.99 × 1.02 × 1.0 = **4.18 km/s**
                
                **Rayleigh bølge:**
                V_Rayleigh = 4.18 / 1.12 = **3.73 km/s**
                
                **Ankomsttider:**
                - Love: 2500 km / 4.18 km/s = **598 s** (9:58)
                - Rayleigh: 2500 km / 3.73 km/s = **670 s** (11:10)
                """)
        
        with tab4:
            st.markdown("### 🧮 Beregn Selv")
            
            col1, col2 = st.columns(2)
            
            with col1:
                calc_magnitude = st.slider("Magnitude:", 4.0, 9.0, 6.5, 0.1)
                calc_depth = st.slider("Dybde (km):", 0, 700, 35, 5)
                calc_distance = st.slider("Afstand (km):", 100, 15000, 2000, 100)
            
            with col2:
                st.markdown("**Valgfri: Vp/Vs fra P/S tider**")
                use_ps = st.checkbox("Brug P/S ankomsttider")
                if use_ps:
                    p_time = st.number_input("P ankomst (s):", 0.0, 3000.0, 300.0, 1.0)
                    s_time = st.number_input("S ankomst (s):", 0.0, 3000.0, 520.0, 1.0)
                else:
                    p_time = None
                    s_time = None
            
            if st.button("Beregn Hastigheder", type="primary"):
                # Brug den faktiske beregningsmetode
                result = self.data_manager.calculate_surface_wave_velocities(
                    distance_km=calc_distance,
                    depth_km=calc_depth,
                    magnitude=calc_magnitude,
                    p_arrival_sec=p_time,
                    s_arrival_sec=s_time
                )
                
                # Vis resultater
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Love hastighed", f"{result['love_velocity']} km/s")
                    st.metric("Love ankomst", f"{result['love_arrival']:.0f} s")
                
                with col2:
                    st.metric("Rayleigh hastighed", f"{result['rayleigh_velocity']} km/s")
                    st.metric("Rayleigh ankomst", f"{result['rayleigh_arrival']:.0f} s")
                
                with col3:
                    factors = result['calculation_factors']
                    st.markdown("**Faktorer:**")
                    st.caption(f"Dybde: {factors['depth_factor']:.2f}")
                    st.caption(f"Afstand: {factors['distance_factor']:.2f}")
                    st.caption(f"Magnitude: {factors['magnitude_factor']:.2f}")
                    if factors['vp_vs_ratio']:
                        st.caption(f"Vp/Vs: {factors['vp_vs_ratio']}")
                        st.caption(f"Type: {factors['structure_type']}")
        
        # Referencer
        with st.expander("Referencer"):
            st.markdown("""
            - Stein, S. & Wysession, M. (2003). *An Introduction to Seismology, Earthquakes, and Earth Structure*
            - Lay, T. & Wallace, T. C. (1995). *Modern Global Seismology*
            - Pasyanos, M. E. (2005). A variable resolution surface wave dispersion study of Eurasia, North Africa, and surrounding regions. *JGR*, 110, B12301.
            - Ekström, G., et al. (2012). The global CMT project 2004–2010: Centroid-moment tensors for 13,017 earthquakes. *Phys. Earth Planet. Inter.*, 200, 1-9.
            """)


    def render_about_view(self):
        """Render about page - Kortfattet version"""
        st.markdown(f"## {texts[st.session_state.language]['nav_about']}")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if st.session_state.language == 'da':
                st.markdown("""
                ### Om GEOseis
                
                GEOseis er et undervisningsværktøj udviklet til det danske gymnasium, 
                der giver direkte adgang til professionelle seismiske data på en overskuelig måde.
                
                **Hovedfunktioner:**
                - Real-time jordskælvsdata fra IRIS
                - Automatisk stationsvalg baseret på afstand
                - Ms magnitude beregning efter IASPEI standarder
                - Interaktive seismogrammer med Plotly
                - Excel eksport til videre analyse i undervisningen
                
                **Pædagogisk værdi:**
                - Arbejde med rigtige videnskabelige data
                - Forståelse af bølgeteori og jordskælv
                - Databehandling og signalanalyse
                - Kritisk tænkning og fortolkning
                """)
            else:
                st.markdown("""
                ### About GEOseis
                
                GEOseis is an educational tool developed for Danish high schools,
                providing direct access to professional seismic data.
                
                **Main features:**
                - Real-time earthquake data from IRIS
                - Automatic station selection based on distance
                - Ms magnitude calculation per IASPEI standards
                - Interactive seismograms with Plotly
                - Excel export for further analysis 
                
                **Educational value:**
                - Work with real scientific data
                - Understanding wave theory and earthquakes
                - Data processing and signal analysis
                - Critical thinking and interpretation
                """)
        
        with col2:
            if st.session_state.language == 'da':
                st.markdown("""
                ### Information
                
                **Version:** 2.0  
                **Udgivet:** Aug 2025
                
                **Udvikler:**  
                Philip Kruse Jakobsen (pj@sg.dk) 
                Silkeborg Gymnasium  
                
                **Teknologi:**  
                - Python / Streamlit
                - ObsPy seismologi
                - IRIS Web Services
                - Plotly visualisering
                
                **Open Source:**  
                Koden er tilgængelig for
                undervisningsbrug.
                """)
            else:
                st.markdown("""
                ### Information
                
                **Version:** 2.0  
                **Released:** Aug. 2025
                
                **Developer:**  
                Philip Kruse Jakobsen (pj@sg.dk) 
                Silkeborg Gymnasium  
                
                **Technology:**  
                - Python / Streamlit
                - ObsPy seismology
                - IRIS Web Services
                - Plotly visualization
                
                **Open Source:**  
                Code is available for
                educational use.
                """)
        
        # Footer
        st.markdown("---")
        if st.session_state.language == 'da':
            st.caption("GEOseis 2.1 - Seismisk analyse til undervisningen")
        else:
            st.caption("GEOseis 2.1 - Seismic analysis for education")

    def run(self):
        """Main application loop"""
        self.load_modern_css()
        self.render_header()
        self.render_sidebar()
        
        # Route to appropriate view
        view_map = {
    'start': self.render_start_view,
    'data_search': self.render_data_search_view,
    'analysis_stations': self.render_analysis_stations_view,
    'unified_analysis': self.render_unified_analysis_view,
    'tools_export': self.render_data_export_view,
    'theory_guide': self.render_theory_guide_view,
    'about': self.render_about_view,
    
}
        
        # Default view er startside
        if st.session_state.current_view not in view_map:
            st.session_state.current_view = 'start'
        
        # Render view
        view_function = view_map.get(st.session_state.current_view, self.render_start_view)
        view_function()


# Main execution
if __name__ == "__main__":
    app = GEOSeisV2()
    app.run()
