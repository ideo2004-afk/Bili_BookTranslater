import google.generativeai as genai
import os

api_key = "AIzaSyBMLx2TjcZNyqVlQRgNxCv2pM1AnAUWWvw"

print(f"Testing API Key: {api_key[:5]}...{api_key[-5:]}")

try:
    genai.configure(api_key=api_key)
    print("Listing models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"Error: {e}")
