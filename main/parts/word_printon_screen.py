import tkinter as tk
from tkinter import font
import time
import threading

input_text = "Hello, this is a typewriter effect demonstration!"

def typewriter_gui(window, label, text, delay=0.05):
    """Updates a Tkinter label with a typewriter effect."""
    label.config(text="") # Clear the label
    for char in text:
        label.config(text=label.cget("text") + char)
        window.update() # Update the window to show changes
        time.sleep(delay)

def run_gui():
    window = tk.Tk()
    
    window.overrideredirect(True)  # Remove window decorations
    window.geometry("400x200")  # Set size and position
    window.configure(bg="black")  # Set background color
    window.wm_attributes("-topmost", True)  # Keep on top
    window.wm_attributes("-transparentcolor", "black")  # Make black transparent

    # Use a bigger font for better visibility
    custom_font = font.Font(family="Helvetica", size=14)
    label = tk.Label(window, text="", font=custom_font, wraplength=380, justify="left")
    label.pack(pady=20)
    label.configure(bg="black", fg="white")  # Set label colors

    # Start the typewriter effect in a separate thread
    def start_animation():
        typewriter_gui(window, label, input_text, 0.05)

    threading.Thread(target=start_animation).start()

    window.mainloop()

# Call the function to start the GUI
run_gui()
