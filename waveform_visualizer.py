# waveform_visualizer.py
"""
Waveform visualisering modul for GEOSeis 2.0
Håndterer plotting af seismiske data med Plotly
"""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Try to import ObsPy for UTCDateTime parsing
try:
    from obspy import UTCDateTime as ObsPyUTCDateTime
    OBSPY_AVAILABLE = True
except ImportError:
    OBSPY_AVAILABLE = False


def parse_arrival_time(arrival_value, eq_time_str=None):
    """
    Parser arrival time fra forskellige formater til sekunder.
    Håndterer UTCDateTime strings, objekter og numeriske værdier.
    """
    if arrival_value is None:
        return None
    
    # Hvis det allerede er et tal, returner det
    if isinstance(arrival_value, (int, float)):
        return float(arrival_value)
    
    # Hvis det er en string
    if isinstance(arrival_value, str):
        # Check for UTCDateTime string format
        if 'UTCDateTime' in arrival_value and OBSPY_AVAILABLE:
            try:
                # Parse UTCDateTime string: "UTCDateTime(2025, 1, 7, 1, 8, 36, 353168)"
                import re
                match = re.search(r'UTCDateTime\((.*?)\)', arrival_value)
                if match:
                    params = [x.strip() for x in match.group(1).split(',')]
                    # Konverter til integers
                    params = [int(p) for p in params]
                    
                    # Opret UTCDateTime objekt
                    arrival_utc = ObsPyUTCDateTime(*params)
                    
                    # Hvis vi har earthquake time, beregn relative sekunder
                    if eq_time_str:
                        try:
                            # Parse earthquake time
                            eq_utc = ObsPyUTCDateTime(eq_time_str)
                            
                            # Returner sekunder fra jordskælv
                            return float(arrival_utc - eq_utc)
                        except Exception as e:
                            print(f"Could not parse earthquake time: {eq_time_str}, error: {e}")
                            pass
                    
                    # Ellers returner som sekunder siden epoch (fallback)
                    return float(arrival_utc.timestamp)
            except Exception as e:
                print(f"Could not parse UTCDateTime string: {arrival_value}, error: {e}")
                return None
    
    # Hvis det er et UTCDateTime objekt
    try:
        if isinstance(arrival_value, ObsPyUTCDateTime) and OBSPY_AVAILABLE:
            if eq_time_str:
                eq_utc = ObsPyUTCDateTime(eq_time_str)
                return float(arrival_value - eq_utc)
            else:
                return float(arrival_value.timestamp)
    except:
        pass
    
    print(f"Could not parse arrival time: {arrival_value} (type: {type(arrival_value)})")
    return None



class WaveformVisualizer:
    """
    Visualiserer seismiske waveforms med Plotly
    Implementerer single-plot med togglebare komponenter som i v1.7
    """
    
    def __init__(self):
        self.default_colors = {
            'north': '#FF6B6B',      # Rød (identisk med v1.7)
            'east': '#4ECDC4',       # Turkis/Grøn 
            'vertical': '#45B7D1'    # Blå
        }
    
    def downsample_data(self, data, max_points=8000, return_indices=False):
        """
        Downsampler data for hurtigere visualisering.
        Identisk med implementering i GEOSeis 1.7
        """
        if len(data) <= max_points:
            if return_indices:
                return data, np.arange(len(data))
            return data
        
        # Beregn downsampling faktor
        factor = len(data) // max_points
        indices = np.arange(0, len(data), factor)[:max_points]
        
        if return_indices:
            return data[indices], indices
        return data[indices]

    def create_waveform_plot(self, waveform_data, show_components=None, 
                            show_arrivals=True, title="Seismogram",
                            height=600):
        """
        Opretter interaktivt seismogram plot med Plotly.
        FIXED: Robust håndtering af filtrerede data arrays.
        """
        try:
            # Default komponenter
            if show_components is None:
                show_components = {'north': True, 'east': True, 'vertical': True}
            
            # Hent displacement data
            displacement_data = waveform_data.get('displacement_data', {})
            if not displacement_data:
                return None
            
            # KRITISK FIX: Valider og konverter alle data til 1D numpy arrays
            cleaned_displacement_data = {}
            for comp_name, comp_data in displacement_data.items():
                if comp_data is not None:
                    # Konverter til numpy array
                    arr = np.array(comp_data)
                    
                    # Sørg for at det er 1D
                    if arr.ndim > 1:
                        print(f"WARNING: {comp_name} has shape {arr.shape}, flattening to 1D")
                        arr = arr.flatten()
                    
                    # Check for valid data
                    if len(arr) > 0 and np.any(np.isfinite(arr)):
                        cleaned_displacement_data[comp_name] = arr
                    else:
                        print(f"WARNING: {comp_name} has no valid data")
            
            displacement_data = cleaned_displacement_data
            
            if not displacement_data:
                print("ERROR: No valid displacement data after cleaning")
                return None
            
            # Hent time arrays
            time_arrays = {}
            times = waveform_data.get('time')
            if times is not None:
                times = np.array(times)
                for comp in displacement_data.keys():
                    data_len = len(displacement_data[comp])
                    if len(times) >= data_len:
                        time_arrays[comp] = times[:data_len]
                    else:
                        # Generer time array baseret på sampling rate
                        sampling_rate = waveform_data.get('sampling_rate', 100)
                        time_arrays[comp] = np.arange(data_len) / sampling_rate
                        print(f"Generated time array for {comp}: {data_len} samples at {sampling_rate} Hz")
            
            # Hent metadata
            units = waveform_data.get('units', 'mm')
            data_label = units
            
            # Parse arrival times
            station_info = waveform_data.get('station_info', {})
            p_arrival = station_info.get('p_arrival')
            s_arrival = station_info.get('s_arrival')
            love_arrival = station_info.get('love_arrival')
            rayleigh_arrival = station_info.get('rayleigh_arrival')
            surface_arrival = station_info.get('surface_arrival')
            
            # Parse arrival times til sekunder
            eq_time = waveform_data.get('earthquake_time')
            
            def parse_arrival_time(arrival, eq_time=None):
                """Parse arrival time til sekunder siden jordskælv"""
                if arrival is None:
                    return None
                try:
                    if isinstance(arrival, str):
                        # Hvis det er en datetime string, konverter til sekunder
                        if 'T' in arrival:
                            from datetime import datetime
                            arrival_dt = datetime.fromisoformat(arrival.replace('Z', '+00:00'))
                            if eq_time:
                                eq_dt = datetime.fromisoformat(eq_time.replace('Z', '+00:00'))
                                return (arrival_dt - eq_dt).total_seconds()
                        else:
                            # Allerede i sekunder
                            return float(arrival)
                    else:
                        return float(arrival)
                except (ValueError, TypeError):
                    return None
            
            p_arrival = parse_arrival_time(p_arrival, eq_time)
            s_arrival = parse_arrival_time(s_arrival, eq_time)
            love_arrival = parse_arrival_time(love_arrival, eq_time)
            rayleigh_arrival = parse_arrival_time(rayleigh_arrival, eq_time)
            surface_arrival = parse_arrival_time(surface_arrival, eq_time)
            
            # INTELLIGENT DOWNSAMPLING FOR VISUALISERING
            max_points = 8000  # Maks punkter for smooth performance
            
            def downsample_for_plotting(times_array, data_array, max_pts=max_points):
                """
                Intelligent downsampling der bevarer peaks og vigtige features.
                Kun til visualisering - original data forbliver uændret.
                """
                if len(data_array) <= max_pts:
                    return times_array, data_array
                
                # Simple downsampling med jævn spacing
                factor = len(data_array) // max_pts
                indices = np.arange(0, len(data_array), factor)[:max_pts]
                
                return times_array[indices], data_array[indices]
            
            # Create figure
            fig = go.Figure()
            
            # Plot hver komponent
            colors = {'north': 'red', 'east': 'green', 'vertical': 'blue'}
            
            for comp_name in ['north', 'east', 'vertical']:
                if comp_name in displacement_data and show_components.get(comp_name, True):
                    data = displacement_data[comp_name]
                    times_arr = time_arrays.get(comp_name, np.arange(len(data)) / waveform_data.get('sampling_rate', 100))
                    
                    # Downsample for plotting performance
                    plot_times, plot_data = downsample_for_plotting(times_arr, data)
                    
                    fig.add_trace(go.Scatter(
                        x=plot_times,
                        y=plot_data,
                        mode='lines',
                        name=comp_name.capitalize(),
                        line=dict(color=colors[comp_name], width=1),
                        visible=show_components.get(comp_name, True)
                    ))
            
            # Tilføj arrival markører hvis requested
            if show_arrivals:
                # P-wave (teoretisk)
                if p_arrival is not None:
                    fig.add_vline(
                        x=p_arrival,
                        line_dash="dash",
                        line_color="red",
                        annotation_text="P (teor.)",
                        annotation_position="top"
                    )
                
                # S-wave (teoretisk)
                if s_arrival is not None:
                    fig.add_vline(
                        x=s_arrival,
                        line_dash="dash",
                        line_color="blue",
                        annotation_text="S (teor.)",
                        annotation_position="top"
                    )
                
                # Love wave (teoretisk)
                if love_arrival is not None:
                    fig.add_vline(
                        x=love_arrival,
                        line_dash="dot",
                        line_color="purple",
                        annotation_text="Love (teor.)",
                        annotation_position="bottom"
                    )
                
                # Rayleigh wave (teoretisk)
                if rayleigh_arrival is not None:
                    fig.add_vline(
                        x=rayleigh_arrival,
                        line_dash="dot",
                        line_color="green",
                        annotation_text="Rayleigh (teor.)",
                        annotation_position="bottom"
                    )
            
            # ENHANCED TITEL - TILFØJET LOGIK:
            try:
                # Kun hvis vi er i Streamlit context og har station info
                import streamlit as st
                if hasattr(st, 'session_state') and 'selected_station' in st.session_state:
                    station = st.session_state.get('selected_station')
                    if station:
                        enhanced_title = get_enhanced_title_info(waveform_data, station)
                        title = f"📍 {enhanced_title}"  # ← ÆNDRET FRA ORIGINAL
            except:
                # Fallback til original titel hvis ikke i Streamlit context
                pass
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title="Tid siden jordskælv (s)",
                yaxis_title=f"Forskydning ({data_label})",
                height=height,
                hovermode='x unified',
                showlegend=True,
                legend=dict(
                    yanchor="top",
                    y=0.99,
                    xanchor="right",
                    x=0.99
                ),
                xaxis=dict(
                    rangeslider=dict(visible=False),
                    type='linear'
                )
            )
            
            # Tilføj jordskælv tidspunkt ved x=0
            fig.add_vline(
                x=0,
                line_width=1,
                line_dash="dot",
                line_color="black",
                annotation_text="Jordskælv",
                annotation_position="bottom"
            )
            
            return fig
            
        except Exception as e:
            print(f"Error creating waveform plot: {e}")
            import traceback
            traceback.print_exc()
            return None

   
    def create_particle_motion_plot(self, waveform_data, time_window=None, max_points=5000):
        """
        Opretter particle motion plots til at identificere bølgetyper.
        Love bølger viser lineær horisontal motion.
        Rayleigh bølger viser elliptisk motion i vertikale planer.
        
        Args:
            waveform_data: Waveform data dictionary
            time_window: Tuple af (start_time, end_time) i sekunder
            max_points: Maksimalt antal punkter at plotte (for performance)
            
        Returns:
            Plotly figure med particle motion plots
        """
        try:
            # Hent displacement data
            displacement_data = waveform_data.get('displacement_data', {})
            if not displacement_data:
                return None
            
            # Hent komponenter
            north = displacement_data.get('north', np.array([]))
            east = displacement_data.get('east', np.array([]))
            vertical = displacement_data.get('vertical', np.array([]))
            
            # Hent time array
            time_array = waveform_data.get('time', np.array([]))
            sampling_rate = waveform_data.get('sampling_rate', 100)
            
            # Anvend tidsvindue hvis specificeret
            if time_window and len(time_array) > 0:
                start_idx = np.argmin(np.abs(time_array - time_window[0]))
                end_idx = np.argmin(np.abs(time_array - time_window[1]))
                
                north = north[start_idx:end_idx] if len(north) > start_idx else north
                east = east[start_idx:end_idx] if len(east) > start_idx else east
                vertical = vertical[start_idx:end_idx] if len(vertical) > start_idx else vertical
                time_array = time_array[start_idx:end_idx]
            
            # Downsample hvis nødvendigt
            if len(north) > max_points:
                indices = np.linspace(0, len(north)-1, max_points, dtype=int)
                north = north[indices]
                east = east[indices]
                vertical = vertical[indices]
            
            # Normaliser data for bedre visualisering
            north_norm = north / (np.max(np.abs(north)) + 1e-10)
            east_norm = east / (np.max(np.abs(east)) + 1e-10)
            vertical_norm = vertical / (np.max(np.abs(vertical)) + 1e-10)
            
            # Opret subplot figure

            fig = make_subplots(
                rows=2, cols=2,
                subplot_titles=(
                    '<b>Horisontal (N-E) - Love bølger</b>',
                    '<b>Vertikal-Nord (Z-N) - Rayleigh bølger</b>',
                    '<b>Vertikal-Øst (Z-E) - Rayleigh bølger</b>',
                    '<b>Bølgetype Indikator</b>'
                ),
                specs=[[{'type': 'scatter'}, {'type': 'scatter'}],
                    [{'type': 'scatter'}, {'type': 'scatter'}]],
                vertical_spacing=0.18,  # Øget for at give plads til titler
                horizontal_spacing=0.1,
                row_heights=[0.5, 0.5],  # Lige højde
                column_widths=[0.5, 0.5]  # Lige bredde
            )


            # Farve gradient baseret på tid
            colors = np.linspace(0, 1, len(north_norm))

            # 1. Horisontal motion (N-E)
            fig.add_trace(
                go.Scatter(
                    x=east_norm,
                    y=north_norm,
                    mode='lines+markers',
                    line=dict(width=2, color='purple'),  # Tykkere linje
                    marker=dict(size=3, color=colors, colorscale='Viridis', showscale=False),  # Større markers
                    name='N-E motion',
                    hovertemplate='E: %{x:.3f}<br>N: %{y:.3f}<extra></extra>'
                ),
                row=1, col=1
            )

            # 2. Vertikal-Nord motion (Z-N)
            fig.add_trace(
                go.Scatter(
                    x=north_norm,
                    y=vertical_norm,
                    mode='lines+markers',
                    line=dict(width=2, color='green'),
                    marker=dict(size=3, color=colors, colorscale='Viridis', showscale=False),
                    name='Z-N motion',
                    hovertemplate='N: %{x:.3f}<br>Z: %{y:.3f}<extra></extra>'
                ),
                row=1, col=2
            )

            # 3. Vertikal-Øst motion (Z-E)
            fig.add_trace(
                go.Scatter(
                    x=east_norm,
                    y=vertical_norm,
                    mode='lines+markers',
                    line=dict(width=2, color='blue'),
                    marker=dict(size=3, color=colors, colorscale='Viridis', showscale=False),
                    name='Z-E motion',
                    hovertemplate='E: %{x:.3f}<br>Z: %{y:.3f}<extra></extra>'
                ),
                row=2, col=1
            )

            # 4. Bølgetype indikator (energi ratio over tid)
            # Beregn glidende vindue energi ratio
            window_size = int(5 * sampling_rate)  # 5 sekunder vindue
            if len(north) > window_size:
                h_energy = []
                v_energy = []
                for i in range(0, len(north) - window_size, window_size//4):
                    h_e = np.sum(north[i:i+window_size]**2 + east[i:i+window_size]**2)
                    v_e = np.sum(vertical[i:i+window_size]**2)
                    h_energy.append(h_e)
                    v_energy.append(v_e)
                
                h_energy = np.array(h_energy)
                v_energy = np.array(v_energy)
                ratio = h_energy / (v_energy + 1e-10)
                
                fig.add_trace(
                    go.Scatter(
                        y=ratio,
                        mode='lines',
                        line=dict(width=3, color='darkred'),  # Tykkere og farvet linje
                        name='H/V ratio',
                        hovertemplate='H/V Ratio: %{y:.2f}<extra></extra>'
                    ),
                    row=2, col=2
                )
                
                # Tilføj reference linjer
                fig.add_hline(y=3.0, line_dash="dash", line_color="purple", line_width=2,
                            annotation_text="Love dominant", annotation_font_size=14, row=2, col=2)
                fig.add_hline(y=0.5, line_dash="dash", line_color="green", line_width=2,
                            annotation_text="Rayleigh dominant", annotation_font_size=14, row=2, col=2)

            # Update axes med større font
            fig.update_xaxes(title_text="Øst", title_font_size=16, tickfont_size=12, row=1, col=1)
            fig.update_yaxes(title_text="Nord", title_font_size=16, tickfont_size=12, row=1, col=1)

            fig.update_xaxes(title_text="Nord", title_font_size=16, tickfont_size=12, row=1, col=2)
            fig.update_yaxes(title_text="Vertikal", title_font_size=16, tickfont_size=12, row=1, col=2)

            fig.update_xaxes(title_text="Øst", title_font_size=16, tickfont_size=12, row=2, col=1)
            fig.update_yaxes(title_text="Vertikal", title_font_size=16, tickfont_size=12, row=2, col=1)

            fig.update_xaxes(title_text="Tid vinduer", title_font_size=16, tickfont_size=12, row=2, col=2)
            fig.update_yaxes(title_text="H/V Energi Ratio", title_font_size=16, tickfont_size=12, type="log", row=2, col=2)

            # Gør alle plots kvadratiske
            # Gør plots kvadratiske med constrain domain
            for row in [1, 2]:
                for col in [1, 2]:
                    if not (row == 2 and col == 2):  # Ikke ratio plottet
                        # Sæt domæne til at være kvadratisk
                        fig.update_xaxes(
                            scaleanchor=f"y{row*2+col-2}", 
                            scaleratio=1,
                            constrain="domain",  # VIGTIG: Tvinger kvadratisk domæne
                            row=row, col=col
                        )
                        fig.update_yaxes(
                            constrain="domain",
                            row=row, col=col
                        )
            # Tilføj grid for bedre læsbarhed
            fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)')
            fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)')

            # Update layout med centreret titel og højere kvalitet
            fig.update_layout(
                height=900,  # Større højde
                title=dict(
                    text="<b>Particle Motion Analyse - Bølgetype Identifikation</b><br>" +
                        "<sup>Lineær horisontal motion indikerer Love bølger, " +
                        "elliptisk motion indikerer Rayleigh bølger</sup>",
                    font=dict(size=18, family="Arial, sans-serif"),  # Større font
                    x=0.5,  # Centrer
                    xanchor='center',
                    y=0.98,
                    yanchor='top'
                ),
                showlegend=False,
                font=dict(size=14),  # Global font størrelse
                plot_bgcolor='white',
                paper_bgcolor='white',
                margin=dict(l=80, r=80, t=120, b=80),  # Mere margin
                # Subplot titler størrelse
                annotations=[
                    dict(font=dict(size=18)) for ann in fig['layout']['annotations']
                ]
            )

            # Opdater subplot titler med større font
            for i in range(len(fig.layout.annotations)):
                fig.layout.annotations[i].font.size = 18

            return fig
        except Exception as e:
            print(f"Error creating particle motion plot: {e}")
            import traceback
            traceback.print_exc()
            return None