import streamlit as st
import requests
import os
import json
import base64
import io
from datetime import datetime, timedelta
import calendar
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_fixed
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import ics
from ics import Calendar, Event

# Load environment variables
load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

if not DEEPSEEK_API_KEY:
    st.error("Error: DEEPSEEK_API_KEY is not set. Please set it in your environment variables.")
    st.stop()

# DeepSeek API endpoint
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"

# Streamlit page configuration
st.set_page_config(
    page_title="Travel Itinerary Planner",
    page_icon="✈️",
    layout="centered",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark theme
st.markdown("""
    <style>
    .stApp {
        background-color: #000;
        color: #fff;
    }
    .stChatMessage {
        background-color: #1a1a1a;
        border-radius: 10px;
        padding: 10px;
        margin-bottom: 10px;
        color: #fff;
    }
    .stButton>button {
        background-color: #007bff;
        color: white;
        border-radius: 5px;
        padding: 5px 15px;
    }
    .stTextInput>div>input {
        background-color: #333;
        color: #fff;
        border-color: #007bff;
        border-radius: 5px;
    }
    .css-1aumxhk {
        display: none;
    }
    .stMarkdown {
        font-family: 'Arial', sans-serif;
        color: #fff;
    }
    .export-section {
        background-color: #1a1a1a;
        padding: 15px;
        border-radius: 10px;
        margin-top: 20px;
    }
    .stExpander {
        border-radius: 10px;
        background-color: #1a1a1a;
    }
    </style>
    """, unsafe_allow_html=True)

# Title and introduction
st.title("✈️ Travel Itinerary Planner")
st.write("Plan your perfect trip with our AI-powered chatbot! Tell me about your trip, and I'll create a personalized itinerary.")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
    # We'll add the system message only when needed to save tokens
    
if "itinerary_data" not in st.session_state:
    st.session_state.itinerary_data = {
        "destination": "",
        "days": 0,
        "start_date": None,
        "activities": {},
        "generated": False
    }
if "itinerary_generated" not in st.session_state:
    st.session_state.itinerary_generated = False
if "full_itinerary_text" not in st.session_state:
    st.session_state.full_itinerary_text = ""
if "api_calls" not in st.session_state:
    st.session_state.api_calls = 0
if "last_query_time" not in st.session_state:
    st.session_state.last_query_time = None
if "use_cached_response" not in st.session_state:
    st.session_state.use_cached_response = False
if "cached_responses" not in st.session_state:
    st.session_state.cached_responses = {}

# Basic common queries and their cached responses
COMMON_QUERIES = {
    "recommend restaurants": "Here are some top restaurant recommendations for your destination:\n\n1. **Local Cuisine** - Always try the regional specialties\n2. **High-rated places** - Check TripAdvisor or Google reviews\n3. **Street Food** - Often the most authentic experience\n4. **Fine Dining** - Make reservations in advance\n\nWould you like me to recommend specific restaurants based on your destination?",
    "what should i pack": "**Essential Packing List:**\n\n- Travel documents (passport, ID, tickets)\n- Appropriate clothing for the climate\n- Comfortable walking shoes\n- Toiletries and medications\n- Phone, charger, and adapter\n- Copy of your itinerary\n- Travel insurance information\n\nFor your specific destination, also consider any special items based on planned activities.",
    "best time to visit": "The best time to visit depends on your destination. Generally:\n\n- Consider shoulder seasons (spring/fall) for better prices and fewer crowds\n- Check seasonal weather patterns for your specific location\n- Be aware of local holidays or festivals that might affect your visit\n\nTell me your specific destination for more tailored advice.",
    "transportation options": "**Common Transportation Options:**\n\n- Public transit (subway, bus, tram)\n- Taxis and rideshare apps\n- Rental cars\n- Bicycles\n- Walking (for smaller cities)\n- Tours and shuttles\n\nThe best option depends on your destination, budget, and comfort level. What's your destination?",
}

# Functions for export options
def create_pdf(itinerary_text, destination):
    """Create a PDF from the itinerary text"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=12,
        textColor=colors.darkblue
    )
    
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Heading2'],
        fontSize=18,
        spaceAfter=8,
        textColor=colors.darkblue
    )
    
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontSize=12,
        spaceAfter=6
    )
    
    # Content elements
    elements = []
    
    # Add title
    elements.append(Paragraph(f"Travel Itinerary: {destination}", title_style))
    elements.append(Spacer(1, 20))
    
    # Process the markdown text
    lines = itinerary_text.split('\n')
    in_list = False
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if line.startswith('# '):
            elements.append(Paragraph(line[2:], title_style))
        elif line.startswith('## '):
            elements.append(Paragraph(line[3:], subtitle_style))
        elif line.startswith('* ') or line.startswith('- '):
            elements.append(Paragraph("• " + line[2:], body_style))
        else:
            elements.append(Paragraph(line, body_style))
    
    # Generate PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer

def create_ics(itinerary_data):
    """Create an ICS calendar file from itinerary data"""
    cal = Calendar()
    
    # Get start date or use today
    start_date = itinerary_data.get("start_date") or datetime.now()
    
    # For each day in the itinerary
    for day_num, activities in itinerary_data.get("activities", {}).items():
        for activity in activities:
            event = Event()
            event.name = activity.get("name", f"Activity on Day {day_num}")
            event.begin = start_date + timedelta(days=int(day_num)-1, hours=activity.get("hour", 9))
            event.duration = timedelta(hours=activity.get("duration", 2))
            event.description = activity.get("description", "")
            event.location = activity.get("location", itinerary_data.get("destination", ""))
            cal.events.add(event)
    
    return cal.serialize()

def extract_itinerary_data(markdown_text):
    """Parse the markdown itinerary to extract structured data"""
    data = {
        "activities": {}
    }
    
    current_day = 0
    lines = markdown_text.split('\n')
    
    for line in lines:
        # Try to extract destination
        if "Itinerary for" in line:
            parts = line.split("Itinerary for")
            if len(parts) > 1:
                data["destination"] = parts[1].strip()
        
        # Try to extract day information
        if line.startswith("## Day") or line.startswith("# Day"):
            try:
                current_day = int(line.split("Day")[1].split(":")[0].strip())
                if current_day not in data["activities"]:
                    data["activities"][current_day] = []
            except:
                pass
        
        # Try to extract activities
        if (line.startswith("- ") or line.startswith("* ")) and current_day > 0:
            activity_text = line[2:].strip()
            if ":" in activity_text:
                time_part, description = activity_text.split(":", 1)
                
                # Try to extract time
                hour = 9  # Default hour
                try:
                    if "AM" in time_part or "PM" in time_part:
                        time_str = time_part.strip()
                        if "AM" in time_str:
                            hour_str = time_str.split("AM")[0].strip()
                            hour = int(hour_str.split(":")[0])
                        elif "PM" in time_str:
                            hour_str = time_str.split("PM")[0].strip()
                            hour = int(hour_str.split(":")[0]) + 12
                except:
                    pass
                
                data["activities"].setdefault(current_day, []).append({
                    "name": description.strip(),
                    "hour": hour,
                    "duration": 2,  # Default duration
                    "description": description.strip(),
                    "location": data.get("destination", "")
                })
    
    return data

# Function to check if query matches a common query
def get_cached_response(query):
    # Check exact matches in our cache
    if query in st.session_state.cached_responses:
        return st.session_state.cached_responses[query]
    
    # Check for common queries that we've pre-cached
    query_lower = query.lower()
    for key, response in COMMON_QUERIES.items():
        if key in query_lower:
            return response
    
    return None

# Display chat history
for message in st.session_state.messages:
    if message.get("role") != "system":  # Don't display system messages
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# Function to call DeepSeek API with streaming (optimized for fewer tokens)
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def call_deepseek(messages, stream=True):
    # Always include the strict system message to enforce travel-only responses
    messages_to_send = [{
        "role": "system", 
        "content": """You are a travel planning expert EXCLUSIVELY focused on creating travel itineraries.
IMPORTANT: You MUST ONLY respond to queries about travel planning, itineraries, or destination information.
For ANY other topics (including technology, news, general knowledge, or non-travel questions):
1. DO NOT provide any information
2. POLITELY redirect the user to ask about travel planning
3. REFUSE to engage with the query
4. EXPLAIN that you are specifically designed only for travel planning

For travel queries:
- Extract destination, days, and preferences from user input
- Ask follow-up questions if needed
- Generate detailed itineraries in markdown with daily activities, dining, and tips
- Be concise and friendly

Remember: You are STRICTLY LIMITED to travel planning assistance ONLY."""
    }]
    
    # Only send relevant context - last few messages to save tokens
    relevant_messages = messages[-4:] if len(messages) > 4 else messages
    messages_to_send.extend([m for m in relevant_messages if m.get("role") != "system"])
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    
    # Use a smaller, faster model for follow-up questions
    model = "deepseek-chat"
    if len(messages) > 2 and st.session_state.itinerary_generated:
        if not any(kw in messages[-1]["content"].lower() for kw in ["itinerary", "plan", "schedule"]):
            model = "deepseek-chat"  # Use a smaller model for simple follow-ups
    
    data = {
        "model": model,
        "messages": messages_to_send,
        "stream": stream,
        "temperature": 0.7,  # Add temperature control
        "max_tokens": 1500  # Limit token usage
    }
    
    try:
        # Increment API call counter
        st.session_state.api_calls += 1
        st.session_state.last_query_time = datetime.now()
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, stream=stream)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        st.error(f"Error: Could not connect to DeepSeek API. Details: {str(e)}")
        return None

# Function to stream text
def stream_text(response):
    full_text = ""
    for line in response.iter_lines():
        if line:
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("data: "):
                data = decoded_line.replace("data: ", "")
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)["choices"][0]["delta"].get("content", "")
                    if chunk:
                        full_text += chunk
                        yield chunk
                except Exception:
                    continue
    return full_text

# Display usage metrics
with st.sidebar:
    st.header("API Usage")
    st.metric("API Calls", st.session_state.api_calls)
    if st.session_state.last_query_time:
        st.text(f"Last query: {st.session_state.last_query_time.strftime('%H:%M:%S')}")
    
    # Toggle for cached responses
    st.checkbox("Use cached responses when available", value=True, key="use_cached_response")
    
    st.markdown("---")

    st.header("How to Use")
    st.markdown("""
    1. **Tell us about your trip** - Include destination, duration, and preferences
    2. **Ask for specific recommendations** - Food, attractions, hidden gems
    3. **Refine your itinerary** - Ask to modify or get more details
    4. **Export your plan** - Download, email, or add to calendar
    """)
    
    st.header("Example Prompts")
    example_prompts = [
        "I'm going to Tokyo for 5 days and love food and technology",
        "Planning a 3-day hiking trip to the Grand Canyon",
        "Weekend getaway to New York with kids",
        "Add more food options to my itinerary"
    ]
    for prompt in example_prompts:
        st.markdown(f"• {prompt}")

# Display the export section if an itinerary has been generated
if st.session_state.itinerary_generated:
    st.markdown("---")
    with st.expander("📤 **Export Your Itinerary**", expanded=True):
        # If we don't have a start date yet, ask for one
        if not st.session_state.itinerary_data.get("start_date"):
            start_date = st.date_input("When does your trip start?", 
                                        datetime.now() + timedelta(days=30),
                                        key="start_date_input")
            if start_date:
                st.session_state.itinerary_data["start_date"] = start_date
        
        col1, col2, col3 = st.columns(3)
        
        # PDF Download
        with col1:
            if st.button("📑 Download as PDF"):
                if st.session_state.full_itinerary_text:
                    try:
                        pdf_buffer = create_pdf(
                            st.session_state.full_itinerary_text, 
                            st.session_state.itinerary_data.get("destination", "Your Trip")
                        )
                        
                        b64_pdf = base64.b64encode(pdf_buffer.read()).decode('utf-8')
                        
                        # Create download link with JavaScript
                        href = f'<a href="data:application/pdf;base64,{b64_pdf}" download="travel_itinerary.pdf" id="pdf_download">Download PDF</a>'
                        
                        # Auto-download with JavaScript
                        download_js = f"""
                        <script>
                            document.addEventListener('DOMContentLoaded', function() {{
                                const link = document.getElementById('pdf_download');
                                if (link) {{
                                    link.click();
                                }}
                            }});
                        </script>
                        """
                        st.markdown(href + download_js, unsafe_allow_html=True)
                        st.success("PDF download started!")
                    except Exception as e:
                        st.error(f"Error creating PDF: {str(e)}")
        
        # Text Download (added as a simpler alternative)
        with col2:
            if st.button("📝 Download as Text"):
                if st.session_state.full_itinerary_text:
                    try:
                        # Convert to plain text
                        text_data = st.session_state.full_itinerary_text
                        b64_text = base64.b64encode(text_data.encode()).decode()
                        
                        # Create download link
                        href = f'<a href="data:text/plain;base64,{b64_text}" download="travel_itinerary.txt" id="text_download">Download Text</a>'
                        
                        # Auto-download
                        download_js = f"""
                        <script>
                            document.addEventListener('DOMContentLoaded', function() {{
                                const link = document.getElementById('text_download');
                                if (link) {{
                                    link.click();
                                }}
                            }});
                        </script>
                        """
                        st.markdown(href + download_js, unsafe_allow_html=True)
                        st.success("Text download started!")
                    except Exception as e:
                        st.error(f"Error creating text file: {str(e)}")
        
        # Calendar export
        with col3:
            if st.button("📅 Add to Calendar"):
                if st.session_state.itinerary_data.get("start_date"):
                    try:
                        # Parse the markdown to extract structured itinerary data
                        if not st.session_state.itinerary_data.get("activities"):
                            structured_data = extract_itinerary_data(st.session_state.full_itinerary_text)
                            st.session_state.itinerary_data.update(structured_data)
                        
                        # Create ICS file
                        ics_data = create_ics(st.session_state.itinerary_data)
                        b64_ics = base64.b64encode(ics_data.encode()).decode()
                        
                        # Create download link
                        href = f'<a href="data:text/calendar;base64,{b64_ics}" download="travel_itinerary.ics" id="ics_download">Download Calendar</a>'
                        
                        # Auto-download
                        download_js = f"""
                        <script>
                            document.addEventListener('DOMContentLoaded', function() {{
                                const link = document.getElementById('ics_download');
                                if (link) {{
                                    link.click();
                                }}
                            }});
                        </script>
                        """
                        st.markdown(href + download_js, unsafe_allow_html=True)
                        st.success("Calendar file download started!")
                    except Exception as e:
                        st.error(f"Error creating calendar file: {str(e)}")
                else:
                    st.error("Please set a start date first")

# Chat input
if prompt := st.chat_input("Tell me about your trip!"):
    # Append user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Standard rejection message for non-travel queries
    rejection_message = """
    I'm specifically designed to help with travel planning and creating itineraries.
    
    I can assist you with:
    • Planning trips to specific destinations
    • Creating custom itineraries based on your preferences
    • Recommending accommodations, attractions, and dining options
    • Providing travel tips and information about destinations
    • Answering questions about transportation options
    
    Please ask me about planning your next trip, and I'll be happy to help!
    """

    # Check if we can use a cached response to save API costs
    cached_response = None
    if st.session_state.use_cached_response:
        cached_response = get_cached_response(prompt)
    
    with st.chat_message("assistant"):
        if cached_response:
            # Use cached response instead of calling API
            st.markdown(cached_response)
            st.session_state.messages.append({"role": "assistant", "content": cached_response})
            # Store in cache for future use
            st.session_state.cached_responses[prompt] = cached_response
        else:
            # Call DeepSeek API
            response = call_deepseek(st.session_state.messages)
            if response is None:
                st.error("API call failed. Please try again.")
                # Remove the failed message from history
                st.session_state.messages.pop()
                st.stop()
            else:
                # Stream the response
                text_generator = stream_text(response)
                output = st.empty()
                full_response = ""
                for chunk in text_generator:
                    full_response += chunk
                    output.markdown(full_response)
                
                # Update message history
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                
                # Cache this response for future similar queries
                st.session_state.cached_responses[prompt] = full_response

                # Check if itinerary has been generated
                if ("itinerary" in full_response.lower() or "day" in full_response.lower()) and not st.session_state.itinerary_generated:
                    if any(day_marker in full_response for day_marker in ["Day 1:", "Day 1 -", "## Day 1", "# Day 1"]):
                        st.session_state.itinerary_generated = True
                        st.session_state.full_itinerary_text = full_response
                        
                        # Try to extract key information
                        extracted_data = extract_itinerary_data(full_response)
                        if extracted_data.get("destination") or extracted_data.get("activities"):
                            st.session_state.itinerary_data.update(extracted_data)
                            st.session_state.itinerary_data["generated"] = True
                        
                        # Rerun to show the export section
                        st.rerun()
