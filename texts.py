"""
Alle tekster til GEOseis applikationen
Redigér denne fil for at ændre tekster på dansk/engelsk
"""

# HOVEDTEKSTER - Redigér disse for at ændre app tekster
texts = {
    'da': {
        # Header
        'app_title': 'GEOseis - Seismisk Analyseplatform',
        'app_subtitle': 'Seismiske data og analyse til undervisning',
        
        # Navigation - ALLE menu punkter
        'nav_home': 'Startside',
        'nav_data': 'Data',
        'nav_station_analysis': 'Station Analyse',
        'nav_tools': 'Værktøjer',
        'nav_help': 'Hjælp & Info',
        'nav_about': 'Om GEOseis',
        
        # Data undermenuer
        'nav_earthquake_search': 'Søg jordskælv',
        'nav_map_view': 'Kortvisning',
        'search_advanced': 'Avanceret søgning',
        
        # Analyse undermenuer
        'nav_waveform_viewer': 'Seismogram',
        'nav_filter_designer': 'Filter Designer',
        'nav_magnitude_calc': 'Magnitude Beregning',
        'analysis_advanced': 'Avanceret analyse',
        
        # Værktøjer undermenuer
        'nav_export': 'Data Export',
        'tools_compare': 'Sammenlign stationer',
        
        # Hjælp undermenuer
        'nav_user_guide': 'Brugervejledning',
        'nav_theory': 'Faglig baggrund',
        'nav_teaching': 'Undervisning',
        'help_technical': 'Teknisk info',
        
        # Velkomstside
        'welcome_title': 'Velkommen til GEOseis',
        'welcome_subtitle': 'Seneste jordskælv M≥6.5',
        'welcome_intro': """
### Interaktiv seismisk analyse platform

GEOseis giver dig mulighed for at:
- **Søge** efter jordskælv fra hele verden
- **Analysere** seismiske data fra hundredvis af stationer
- **Beregne** magnituder og identificere bølgetyper
- **Eksportere** data til undervisning og forskning

Start med at udforske de seneste store jordskælv på kortet nedenfor, 
eller brug menuen til venstre for at søge efter specifikke jordskælv.
        """,
        
        # Features
        'main_features': 'Hovedfunktioner',
        'feature_data_title': 'Data Access',
        'feature_data_text': 'Direkte adgang til globale seismiske data fra IRIS netværket med over 1000 stationer verden over.',
        'feature_analysis_title': 'Analyse Værktøjer',
        'feature_analysis_text': 'Professionelle værktøjer til signal processing, filtrering og magnitude beregning.',
        'feature_export_title': 'Export & Deling',
        'feature_export_text': 'Eksporter data og resultater til Excel for videre analyse eller undervisningsbrug.',
        
        # Data søgning
        'search_title': 'Søg efter jordskælv',
        'search_criteria': 'Definer søgekriterier',
        'magnitude_range': 'Magnitude område',
        'magnitude_help': 'Vælg minimum og maksimum magnitude',
        'date_range': 'Årstal',
        'date_help': 'Vælg start og slut år',
        'depth_range': 'Dybde (km)',
        'depth_help': 'Vælg minimum og maksimum dybde',
        'max_results': 'Maksimalt antal resultater',
        'search_button': 'Søg',
        'reset_button': 'Nulstil',
        
        # Seismogram
        'waveform_title': 'Seismogram',
        
        # Generelle
        'loading': 'Indlæser...',
        'loading_earthquakes': 'Henter jordskælvsdata...',
        'error': 'Fejl',
        'warning': 'Advarsel',
        'info': 'Information',
        'close': 'Luk',
        'save': 'Gem',
        'cancel': 'Annuller',
        'back': 'Tilbage',
        'next': 'Næste',
    },
    'en': {
        # Header
        'app_title': 'GEOseis - Seismic Analysis Platform',
        'app_subtitle': 'Seismic data and analysis for education',
        
        # Navigation - ALL menu items
        'nav_home': 'Home',
        'nav_data': 'Data',
        'nav_station_analysis': 'Station Analysis',
        'nav_tools': 'Tools',
        'nav_help': 'Help & Info',
        'nav_about': 'About GEOseis',
        
        # Data submenus
        'nav_earthquake_search': 'Search earthquakes',
        'nav_map_view': 'Map view',
        'search_advanced': 'Advanced search',
        
        # Analysis submenus
        'nav_waveform_viewer': 'Seismogram',
        'nav_filter_designer': 'Filter Designer',
        'nav_magnitude_calc': 'Magnitude Calculation',
        'analysis_advanced': 'Advanced analysis',
        
        # Tools submenus
        'nav_export': 'Data Export',
        'tools_compare': 'Compare stations',
        
        # Help submenus
        'nav_user_guide': 'User Guide',
        'nav_theory': 'Theory Background',
        'nav_teaching': 'Teaching',
        'help_technical': 'Technical info',
        
        # Welcome page
        'welcome_title': 'Welcome to GEOseis',
        'welcome_subtitle': 'Latest earthquakes M≥6.5',
        'welcome_intro': """
### Interactive seismic analysis platform

GEOseis allows you to:
- **Search** for earthquakes from around the world
- **Analyze** seismic data from hundreds of stations
- **Calculate** magnitudes and identify wave types
- **Export** data for teaching and research

Start by exploring recent major earthquakes on the map below,
or use the menu on the left to search for specific earthquakes.
        """,
        
        # Features
        'main_features': 'Main Features',
        'feature_data_title': 'Data Access',
        'feature_data_text': 'Direct access to global seismic data from the IRIS network with over 1000 stations worldwide.',
        'feature_analysis_title': 'Analysis Tools',
        'feature_analysis_text': 'Professional tools for signal processing, filtering and magnitude calculation.',
        'feature_export_title': 'Export & Sharing',
        'feature_export_text': 'Export data and results to Excel for further analysis or educational use.',
        
        # Data search
        'search_title': 'Search for earthquakes',
        'search_criteria': 'Define search criteria',
        'magnitude_range': 'Magnitude range',
        'magnitude_help': 'Select minimum and maximum magnitude',
        'date_range': 'Year range',
        'date_help': 'Select start and end year',
        'depth_range': 'Depth (km)',
        'depth_help': 'Select minimum and maximum depth',
        'max_results': 'Maximum number of results',
        'search_button': 'Search',
        'reset_button': 'Reset',
        
        # Seismogram
        'waveform_title': 'Seismogram',
        
        # General
        'loading': 'Loading...',
        'loading_earthquakes': 'Loading earthquake data...',
        'error': 'Error',
        'warning': 'Warning',
        'info': 'Information',
        'close': 'Close',
        'save': 'Save',
        'cancel': 'Cancel',
        'back': 'Back',
        'next': 'Next',
    }
}

# HJÆLPETEKSTER - Længere forklaringer
help_texts = {
    'da': {
        'getting_started': """
## Kom godt i gang med GEOseis

### 1. Find et jordskælv
- Gå til **Data** i menuen
- Justér søgeparametre (magnitude, dato, dybde)
- Klik på **Søg** knappen

### 2. Vælg en station
- Systemet finder automatisk nærliggende stationer
- Vælg en station fra listen
- Check datatilgængelighed

### 3. Analysér data
- Se seismogrammer for alle tre komponenter
- Anvend filtre for at fremhæve forskellige bølgetyper
- Beregn Ms magnitude fra overfladebølger

### 4. Eksportér resultater
- Download data som Excel fil
- Inkludér metadata og beregninger
- Brug til undervisning eller videre analyse
        """,
        'wave_types': """
### P-bølger (Primære bølger)
- Hastighed: 6-8 km/s i jordskorpen
- Første bølger der ankommer
- Bevægelse: Frem og tilbage

### S-bølger (Sekundære bølger)  
- Hastighed: 3-4 km/s i jordskorpen
- Større amplitude end P-bølger
- Bevægelse: Op/ned og side til side

### Overfladebølger
- Hastighed: ~3.5 km/s
- Største amplitude
- Bruges til Ms magnitude beregning
        """
    },
    'en': {
        'getting_started': """
## Getting Started with GEOseis

### 1. Find an earthquake
- Go to **Data** in the menu
- Adjust search parameters (magnitude, date, depth)
- Click the **Search** button

### 2. Select a station
- System automatically finds nearby stations
- Choose a station from the list
- Check data availability

### 3. Analyze data
- View seismograms for all three components
- Apply filters to highlight different wave types
- Calculate Ms magnitude from surface waves

### 4. Export results
- Download data as Excel file
- Include metadata and calculations
- Use for teaching or further analysis
        """,
        'wave_types': """
### P-waves (Primary waves)
- Speed: 6-8 km/s in the crust
- First waves to arrive
- Motion: Back and forth

### S-waves (Secondary waves)
- Speed: 3-4 km/s in the crust
- Larger amplitude than P-waves
- Motion: Up/down and side to side

### Surface waves
- Speed: ~3.5 km/s
- Largest amplitude
- Used for Ms magnitude calculation
        """
    }
}