#!/usr/bin/env python3
"""
Email Processing Desktop Widget

A minimal desktop widget that displays:
- Total emails processed
- Minutes since last email
- Active scan status

Auto-refreshes every 10 seconds and stays on top of other windows.
"""

import json
import tkinter as tk
from datetime import datetime
from urllib.request import urlopen

API_URL = "https://crm-hth-0f0e9a31256d.herokuapp.com/dashboard/stats"
REFRESH_INTERVAL = 10000  # 10 seconds in milliseconds


class EmailWidget:
    def __init__(self, root):
        self.root = root
        self.root.title("Email Stats")

        # Window configuration
        self.root.attributes("-topmost", True)  # Always on top
        self.root.configure(bg="#667eea")
        self.root.resizable(False, False)

        # Make window semi-transparent (macOS)
        try:
            self.root.attributes("-alpha", 0.95)
        except:
            pass

        # Main container
        self.container = tk.Frame(root, bg="#667eea", padx=20, pady=20)
        self.container.pack()

        # Title
        self.title_label = tk.Label(
            self.container,
            text="📧 Email Processing",
            font=("Helvetica", 18, "bold"),
            bg="#667eea",
            fg="white",
        )
        self.title_label.pack(pady=(0, 15))

        # Stats frame
        self.stats_frame = tk.Frame(self.container, bg="white", padx=20, pady=20)
        self.stats_frame.pack(fill="both", expand=True)

        # Total emails stat
        self.total_label = tk.Label(
            self.stats_frame,
            text="TOTAL EMAILS",
            font=("Helvetica", 10, "bold"),
            bg="white",
            fg="#718096",
        )
        self.total_label.pack(anchor="w", pady=(0, 5))

        self.total_value = tk.Label(
            self.stats_frame, text="—", font=("Helvetica", 36, "bold"), bg="white", fg="#2d3748"
        )
        self.total_value.pack(anchor="w", pady=(0, 15))

        # Minutes since last email
        self.minutes_label = tk.Label(
            self.stats_frame,
            text="MINUTES SINCE LAST",
            font=("Helvetica", 10, "bold"),
            bg="white",
            fg="#718096",
        )
        self.minutes_label.pack(anchor="w", pady=(0, 5))

        self.minutes_value = tk.Label(
            self.stats_frame, text="—", font=("Helvetica", 36, "bold"), bg="white", fg="#2d3748"
        )
        self.minutes_value.pack(anchor="w", pady=(0, 15))

        # Status
        self.status_frame = tk.Frame(self.stats_frame, bg="#f7fafc", padx=10, pady=8)
        self.status_frame.pack(fill="x")

        self.status_dot = tk.Label(
            self.status_frame, text="●", font=("Helvetica", 16), bg="#f7fafc", fg="#a0aec0"
        )
        self.status_dot.pack(side="left", padx=(0, 8))

        self.status_text = tk.Label(
            self.status_frame, text="Loading...", font=("Helvetica", 11), bg="#f7fafc", fg="#4a5568"
        )
        self.status_text.pack(side="left")

        # Last updated
        self.updated_label = tk.Label(
            self.container, text="Updated just now", font=("Helvetica", 9), bg="#667eea", fg="white"
        )
        self.updated_label.pack(pady=(10, 0))

        # Close button (small x in corner)
        self.close_button = tk.Button(
            self.container,
            text="✕",
            command=self.root.quit,
            font=("Helvetica", 12),
            bg="#667eea",
            fg="white",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
        self.close_button.place(x=10, y=10)

        # Start updating
        self.update_stats()

    def update_stats(self):
        """Fetch and display latest stats."""
        try:
            # Fetch data
            response = urlopen(API_URL, timeout=5)
            data = json.loads(response.read())

            # Update total emails
            total = data.get("total_emails", 0)
            self.total_value.config(text=f"{total:,}")

            # Update minutes since last email
            minutes = data.get("minutes_since_last_email")
            if minutes is not None:
                self.minutes_value.config(text=str(minutes))

                # Color code based on freshness
                if minutes < 5:
                    color = "#48bb78"  # Green
                elif minutes < 15:
                    color = "#ed8936"  # Orange
                else:
                    color = "#f56565"  # Red

                self.minutes_value.config(fg=color)
            else:
                self.minutes_value.config(text="—", fg="#2d3748")

            # Update status
            active_scans = data.get("active_scans", 0)
            progress = data.get("current_job_progress")

            if active_scans > 0:
                self.status_dot.config(fg="#48bb78")
                status_text = f"Scanning ({progress}%)" if progress else "Scanning..."
                self.status_text.config(text=status_text)
            else:
                self.status_dot.config(fg="#a0aec0")
                self.status_text.config(text="Idle")

            # Update timestamp
            now = datetime.now().strftime("%I:%M:%S %p")
            self.updated_label.config(text=f"Updated at {now}")

        except Exception as e:
            print(f"Error fetching stats: {e}")
            self.status_text.config(text="Error loading stats")

        # Schedule next update
        self.root.after(REFRESH_INTERVAL, self.update_stats)


def main():
    """Create and run the widget."""
    root = tk.Tk()

    # Position window in top-right corner
    screen_width = root.winfo_screenwidth()
    window_width = 320
    x_position = screen_width - window_width - 20
    y_position = 20

    root.geometry(f"{window_width}x450+{x_position}+{y_position}")

    # Create widget
    app = EmailWidget(root)

    # Run
    print("🚀 Email widget running...")
    print("📊 Window positioned in top-right corner")
    print("🔄 Auto-refreshing every 10 seconds")
    print("❌ Click the X button to close")

    root.mainloop()


if __name__ == "__main__":
    main()
