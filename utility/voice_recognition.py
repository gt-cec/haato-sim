try:
    import speech_recognition as sr
except ImportError:
    pass
import time


def listen_for_human_voice(xpc):
    try:
        recognizer = sr.Recognizer()
        microphone = sr.Microphone()
        with microphone as source:
            audio = recognizer.listen(source, timeout=2, phrase_time_limit=45)

            # Convert speech to text using Google Speech Recognition
            human_query = recognizer.recognize_google(audio)
            print(f'\n##################### You said: {human_query}\n #####################')

        if "status" in human_query and ("wingman" in human_query or "lead" in human_query):
            print(f'Detected status request')
            xpc.sendDREF("custom/haato/human_messages", 1.0)

        elif "plan" and "request" in human_query:
            print(f'Detected plan request')
            xpc.sendDREF("custom/haato/human_messages", 2.0)
            xpc.sendDREF("custom/haato/human_requests_plan_suggestion", 1.0)
    except Exception as e:
        pass

def voice_recognition_loop(xpc):
    """Continuous loop for the voice recognition thread."""
    print("Voice recognition thread started.")
    while True:
        listen_for_human_voice(xpc)
        # Small sleep to prevent high CPU usage if an error occurs
        time.sleep(0.1)