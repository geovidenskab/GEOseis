# toast_manager.py
"""
Toast notification system for GEOSeis
Diskret feedback system med hvid baggrund og farvet venstre kant
"""

import streamlit as st
import time

class ToastManager:
    """
    Diskret toast manager med hvid baggrund og farvet venstre kant.
    Matcher bredden af filter-søjlen (ca. 350px).
    """
    
    def __init__(self):
        self.last_message = None
        self.last_time = 0
        self.shown_messages = set()  # Track viste beskeder
        self.session_key = None  # Track current session (station/earthquake)
        # Toast counter for unique IDs
        if 'toast_counter' not in st.session_state:
            st.session_state.toast_counter = 0
    
    def set_session_key(self, key):
        """Set ny session key - rydder shown messages når ny station vælges."""
        if key != self.session_key:
            self.shown_messages.clear()
            self.session_key = key
    
    def show_banner(self, message, banner_type='info', duration=3.0, details=None, once_per_session=False):
        """Show diskret toast med hvid baggrund og farvet kant."""
        import streamlit as st
        import time
        
        # Kombiner message og details
        full_message = message
        if details:
            full_message = f"{message} - {details}"
        
        # Check om beskeden allerede er vist i denne session
        if once_per_session:
            message_key = f"{message}_{details}"
            if message_key in self.shown_messages:
                return  # Skip hvis allerede vist
            self.shown_messages.add(message_key)
        
        # Ikon og farver baseret på type
        type_config = {
            'success': {
                'icon': '✓',  # Mindre diskret checkmark
                'border_color': '#28a745',  # Grøn
                'text_color': '#155724'
            },
            'error': {
                'icon': '×',  # Diskret X
                'border_color': '#dc3545',  # Rød
                'text_color': '#721c24'
            },
            'warning': {
                'icon': '!',  # Diskret udråbstegn
                'border_color': '#ffc107',  # Gul
                'text_color': '#856404'
            },
            'info': {
                'icon': 'i',  # Diskret i
                'border_color': '#17a2b8',  # Blå
                'text_color': '#0c5460'
            },
            'loading': {
                'icon': '⋯',  # Diskrete prikker
                'border_color': '#6c757d',  # Grå
                'text_color': '#383d41'
            }
        }
        
        config = type_config.get(banner_type, type_config['info'])
        
        # Undgå duplikater
        current_time = time.time()
        if self.last_message == full_message and (current_time - self.last_time) < 2:
            return  # Skip duplicate
        
        # Unique toast ID
        toast_id = f"toast-{st.session_state.toast_counter}"
        st.session_state.toast_counter += 1
        
        # Duration i millisekunder
        duration_ms = int(duration * 1000)
        
        # HTML og JavaScript - MEGET diskret design
        st.markdown(f"""
        <div id="{toast_id}" style="
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: white;
            padding: 10px 12px;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            z-index: 1000;
            font-size: 13px;
            font-weight: 400;
            animation: slideInBottom 0.3s ease-out;
            max-width: 250px;
            width: 250px;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            border-left: 3px solid {config['border_color']};
            color: {config['text_color']};
            display: flex;
            align-items: center;
            gap: 8px;
        ">
            <span style="
                font-weight: 600;
                font-size: 14px;
                width: 16px;
                height: 16px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                background: {config['border_color']}20;
                color: {config['border_color']};
                flex-shrink: 0;
            ">{config['icon']}</span>
            <span style="flex: 1; line-height: 1.4;">{full_message}</span>
        </div>
        
        <style>
        @keyframes slideInBottom {{
            from {{ 
                transform: translateY(20px); 
                opacity: 0; 
            }}
            to {{ 
                transform: translateY(0); 
                opacity: 1; 
            }}
        }}
        @keyframes fadeOut {{
            from {{ 
                opacity: 1; 
            }}
            to {{ 
                opacity: 0; 
            }}
        }}
        </style>
        
        <script>
        setTimeout(function() {{
            const toast = document.getElementById('{toast_id}');
            if (toast) {{
                toast.style.animation = 'fadeOut 0.2s ease-out';
                setTimeout(function() {{
                    toast.remove();
                }}, 200);
            }}
        }}, {duration_ms});
        </script>
        """, unsafe_allow_html=True)
        
        # Opdater tracking
        self.last_message = full_message
        self.last_time = current_time
    
    def show(self, message, toast_type='info', duration=3.0, context=None, once_per_session=False):
        """Alias for show_banner."""
        # Default duration hvis None
        if duration is None:
            duration = 3.0
        self.show_banner(message, banner_type=toast_type, duration=duration, 
                        details=context, once_per_session=once_per_session)
    
    def render_banner(self):
        """Compatibility method - does nothing with this implementation."""
        pass
    
    def render(self):
        """Compatibility method - does nothing with this implementation."""
        pass
    
    def clear_banners(self):
        """Compatibility method - does nothing with this implementation."""
        pass
    
    def clear(self):
        """Compatibility method - does nothing with this implementation."""
        pass