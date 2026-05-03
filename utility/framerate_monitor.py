import matplotlib.pyplot as plt
import csv
import os


class FramerateMonitor:
    """Monitor and visualize X-Plane framerate periods over simulation steps."""

    def __init__(self, xpc, csv_filename="framerate_log.csv"):
        """
        Initialize the framerate monitor.

        Args:
            xpc: XPlaneConnect instance for communicating with X-Plane
            csv_filename: Name of the CSV file to write data to
        """
        self.xpc = xpc
        self.data = []  # List of (framerate_period, step_number) tuples
        self.csv_filename = csv_filename

        # Create CSV file with headers if it doesn't exist
        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['step_number', 'framerate_period'])

    def log_fps(self, step_number):
        """
        Log the current framerate period at the given step number.
        Writes to CSV file every 5 steps.

        Args:
            step_number: The current simulation step number
        """
        framerate_period = self.xpc.getDREF("sim/time/framerate_period")
        self.data.append((framerate_period, step_number))

        # Write to CSV every 5 steps
        if step_number % 5 == 0:
            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([step_number, framerate_period])

    def plot(self):
        """
        Generate a matplotlib plot of framerate period vs step number.
        """
        if not self.data:
            print("No data to plot. Call log_fps() first.")
            return

        # Close any existing plots
        plt.close('all')

        # Unpack data
        framerate_periods, step_numbers = zip(*self.data)

        # Create the plot
        plt.figure(figsize=(10, 6))
        plt.plot(step_numbers, framerate_periods, marker='o', linestyle='-', linewidth=2, markersize=4)
        plt.xlabel('Step Number', fontsize=12)
        plt.ylabel('Framerate Period (seconds)', fontsize=12)
        plt.title('X-Plane Framerate Period vs Simulation Step', fontsize=14)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

    def clear(self):
        """Clear all logged data."""
        self.data = []

    def get_stats(self):
        """
        Get statistics about the logged framerate periods.

        Returns:
            dict: Statistics including min, max, mean, and count
        """
        if not self.data:
            return {"error": "No data logged"}

        framerate_periods = [fp for fp, _ in self.data]
        return {
            "min_period": min(framerate_periods),
            "max_period": max(framerate_periods),
            "mean_period": sum(framerate_periods) / len(framerate_periods),
            "count": len(framerate_periods)
        }


# Example usage:
if __name__ == "__main__":
    # This is a demonstration of how to use the FramerateMonitor
    # You would need to have XPlaneConnect installed and X-Plane running

    try:
        from xpc import XPlaneConnect

        # Connect to X-Plane
        xpc = XPlaneConnect()

        # Create monitor
        monitor = FramerateMonitor(xpc)

        # Log framerate over multiple steps
        for step in range(100):
            monitor.log_fps(step)

        # Display statistics
        print("Framerate Statistics:")
        print(monitor.get_stats())

        # Plot the results
        monitor.plot()

    except ImportError:
        print("XPlaneConnect not installed. Install with: pip install xpc")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure X-Plane is running and the XPlaneConnect plugin is installed.")