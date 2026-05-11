"""
Smart Grid Digital Twin – a 24-hour city microgrid simulation.
All logic and UI are in this single file to keep things simple.
"""

import streamlit as st
import math
import pandas as pd

# ------------------------------------------------------------
# 1. BATTERY CLASS
# ------------------------------------------------------------
class Battery:
    """
    A simple battery with capacity (kWh), current charge (kWh),
    and 90 % efficiency on both charge and discharge.
    """
    def __init__(self, capacity_kwh):
        self.capacity = capacity_kwh # max energy it can hold
        self.current_charge = capacity_kwh * 0.5 # start at 50 % full
        self.efficiency = 0.9 # 10 % loss on every transfer

    def charge(self, amount_kwh):
        """Add energy to the battery. 10 % is lost as heat."""
        if amount_kwh <= 0:
            return
        # Only 90 % of the incoming energy actually gets stored
        energy_to_store = amount_kwh * self.efficiency
        # Don't exceed capacity
        space_left = self.capacity - self.current_charge
        energy_stored = min(energy_to_store, space_left)
        self.current_charge += energy_stored

    def discharge(self, amount_kwh):
        """
        Take energy from the battery.
        Returns the usable energy delivered (after 10 % loss),
        or as much as possible if the battery runs out.
        """
        if amount_kwh <= 0 or self.current_charge <= 0:
            return 0.0

        # We can only withdraw what is actually stored
        taken_from_storage = min(amount_kwh, self.current_charge)
        self.current_charge -= taken_from_storage
        # 10 % of the stored energy is lost during discharge
        delivered = taken_from_storage * self.efficiency
        return delivered

# ------------------------------------------------------------
# 2. BUILDING DEFINITIONS
# ------------------------------------------------------------
def create_buildings(num_houses):
    """
    Returns a list of building dictionaries.
    Each building has a name, base demand (kW) and priority (1=highest).
    Residential demand scales with the number of houses.
    """
    # Fixed demands for hospital and factory
    hospital = {"name": "Hospital", "demand_kw": 60, "priority": 1}
    industrial = {"name": "Factory", "demand_kw": 80, "priority": 3}
    # Residential: each house consumes 2 kW (constant over the day)
    residential = {
        "name": "Residential",
        "demand_kw": num_houses * 2,
        "priority": 2,
    }
    # Sort by priority (1 first, 3 last)
    return sorted([hospital, residential, industrial], key=lambda b: b["priority"])

# ------------------------------------------------------------
# 3. SOLAR GENERATION (Lambert's Cosine Law)
# ------------------------------------------------------------
def solar_power_kw(hour, panel_area_m2):
    """
    Returns solar power (kW) for a given hour (0–23).
    Uses Lambert's cosine law: intensity ∝ cos(solar zenith angle).
    Assumptions:
      - Solar noon at hour 12 (angle = 0°)
      - Peak irradiance = 1.0 kW/m²
      - Panel efficiency = 20 %
    """
    if hour < 6 or hour > 18:
        return 0.0 # no sun before 6 am or after 6 pm

    # Hour angle: each hour offset from noon = 15 degrees
    angle_deg = (hour - 12) * 15
    angle_rad = math.radians(angle_deg)
    cos_theta = math.cos(angle_rad)

    if cos_theta <= 0:
        return 0.0

    peak_irradiance = 1.0 # kW per m²
    panel_efficiency = 0.2 # 20 %
    power = peak_irradiance * cos_theta * panel_area_m2 * panel_efficiency
    return power

# ------------------------------------------------------------
# 4. THE 24‑HOUR SIMULATION
# ------------------------------------------------------------
def run_simulation(panel_area, battery_capacity, num_houses):
    """
    Runs the microgrid simulation for 24 hours.
    Returns a dictionary with hourly logs and aggregated KPIs.
    """
    # Set up buildings and battery
    buildings = create_buildings(num_houses)
    battery = Battery(battery_capacity)

    # Storage for results
    hours = []
    solar_list = []
    demand_list = []
    grid_import_list = []
    battery_soc_list = []
    solar_direct_total = 0.0 # solar energy used immediately
    battery_delivered_total = 0.0 # solar energy taken from battery
    grid_total = 0.0
    hospital_no_grid_count = 0 # hours the hospital ran without grid

    for hour in range(24):
        # ---- a) Solar generation this hour ----
        solar = solar_power_kw(hour, panel_area)
        solar_remaining = solar # solar still available this hour

        # ---- b) Total demand this hour ----
        total_demand = sum(b["demand_kw"] for b in buildings)

        # ---- c) Serve demand in priority order ----
        hour_grid = 0.0
        hour_battery_delivered = 0.0
        hospital_used_grid = False # flag for this hour

        for building in buildings:
            need = building["demand_kw"]

            # 1) Use solar first
            solar_use = min(need, solar_remaining)
            need -= solar_use
            solar_remaining -= solar_use
            solar_direct_total += solar_use

            # 2) If still needed, use battery
            if need > 0:
                batt_delivered = battery.discharge(need)
                need -= batt_delivered
                hour_battery_delivered += batt_delivered

            # 3) Whatever remains must come from the grid
            if need > 0:
                hour_grid += need
                # If this is the hospital, note that grid was used
                if building["name"] == "Hospital":
                    hospital_used_grid = True

        battery_delivered_total += hour_battery_delivered
        grid_total += hour_grid

        # Track hospital hours without any grid usage
        if not hospital_used_grid:
            hospital_no_grid_count += 1

        # ---- d) Charge battery with excess solar ----
        if solar_remaining > 0:
            battery.charge(solar_remaining) # 10 % loss inside charge()

        # ---- e) Record hourly data ----
        hours.append(hour)
        solar_list.append(solar)
        demand_list.append(total_demand)
        grid_import_list.append(hour_grid)
        battery_soc_list.append(battery.current_charge)

    # ---- f) Final KPIs ----
    total_solar_consumed = solar_direct_total + battery_delivered_total
    co2_saved_kg = total_solar_consumed * 0.45 # 0.45 kg CO₂ per kWh
    hospital_uptime_pct = (hospital_no_grid_count / 24) * 100

    return {
        "hourly": {
            "hour": hours,
            "solar_kw": solar_list,
            "demand_kw": demand_list,
            "grid_import_kw": grid_import_list,
            "battery_soc_kwh": battery_soc_list,
        },
        "kpi": {
            "co2_saved_kg": co2_saved_kg,
            "hospital_uptime_pct": hospital_uptime_pct,
            "grid_reliance_kwh": grid_total,
            "total_solar_consumed_kwh": total_solar_consumed,
        },
    }

# ------------------------------------------------------------
# 5. STREAMLIT DASHBOARD (the human‑friendly frontend)
# ------------------------------------------------------------
def main():
    st.set_page_config(page_title="Smart Grid Digital Twin", layout="wide")
    st.title("🏙️ Smart Grid Digital Twin")
    st.markdown(
        "Simulate a 24‑hour city microgrid with solar, battery, "
        "and priority‑based load management."
    )

    # ----- Sidebar controls -----
    with st.sidebar:
        st.header("🔧 Adjust Parameters")
        panel_area = st.slider(
            "Solar Panel Area (m²)",
            min_value=100, max_value=2000, value=500, step=50,
            help="Total area of solar panels installed."
        )
        battery_capacity = st.slider(
            "Battery Capacity (kWh)",
            min_value=50, max_value=1000, value=200, step=50,
            help="Usable capacity of the battery storage."
        )
        num_houses = st.slider(
            "City Size (Number of Houses)",
            min_value=10, max_value=200, value=50, step=10,
            help="Number of residential houses – each consumes 2 kW constantly."
        )

        run_clicked = st.button("▶️ Run Simulation", type="primary")

    # ----- Run simulation on button click -----
    if run_clicked:
        with st.spinner("Simulating 24 hours…"):
            results = run_simulation(panel_area, battery_capacity, num_houses)
            st.session_state["results"] = results
            st.success("Simulation complete!")

    # ----- Display results if available -----
    if "results" in st.session_state:
        res = st.session_state["results"]
        hourly = res["hourly"]
        kpi = res["kpi"]

        # ---- Build DataFrames for plotting ----
        df_balance = pd.DataFrame({
            "Hour": hourly["hour"],
            "Solar Generation (kW)": hourly["solar_kw"],
            "Total Demand (kW)": hourly["demand_kw"],
            "Grid Import (kW)": hourly["grid_import_kw"],
        }).set_index("Hour")

        df_battery = pd.DataFrame({
            "Hour": hourly["hour"],
            "Battery SOC (kWh)": hourly["battery_soc_kwh"],
        }).set_index("Hour")

        # ---- Charts ----
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("⚡ Energy Supply vs. Total Demand")
            st.line_chart(df_balance)

        with col2:
            st.subheader("🔋 Battery State of Charge")
            st.line_chart(df_battery)

        # ---- KPI Scorecards ----
        st.subheader("📊 Sustainability Metrics")
        k1, k2, k3 = st.columns(3)
        k1.metric("🌱 Total CO₂ Saved (kg)", f"{kpi['co2_saved_kg']:.1f}")
        k2.metric("🏥 Hospital Uptime (no grid)", f"{kpi['hospital_uptime_pct']:.1f} %")
        k3.metric("🔌 Grid Reliance (kWh)", f"{kpi['grid_reliance_kwh']:.1f}")

        # Small additional note
        st.caption(
            "Hospital uptime shows the percentage of hours the hospital "
            "ran entirely on local solar + battery (no grid needed)."
        )

# ------------------------------------------------------------
# 6. RUN THE APP
# ------------------------------------------------------------
if __name__ == "__main__":
    main()