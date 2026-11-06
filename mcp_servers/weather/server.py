import httpx
from mcp.server.fastmcp import FastMCP

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo returns WMO weather codes; map the common ones to words
WEATHER_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "rain showers", 81: "rain showers", 82: "heavy rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}

mcp = FastMCP("weather")


def _search(name: str, count: int) -> list[dict]:
    geo = httpx.get(GEOCODE_URL, params={"name": name, "count": count}, timeout=10).json()
    return geo.get("results") or []


def find_place(city: str) -> dict | None:
    """The first geocoding match for `city`, or None.
    The geocoder doesn't know German "town-district" names like "Albstadt-Ebingen".
    When the full name finds nothing, search each part and keep a result only if the
    other part is its town or region (Ebingen lies in Albstadt), so a made-up name
    like "Nowhere-Xyzzy" never turns into some other place's weather."""
    city = city.strip()
    found = _search(city, 1)
    if found or "-" not in city:
        return found[0] if found else None
    parts = [p.strip() for p in city.split("-") if p.strip()]
    for part in parts[::-1]:   # the district (last part) first
        others = {p.lower() for p in parts if p != part}
        for place in _search(part, 10):
            region = {str(v).lower() for k, v in place.items() if k.startswith("admin") and isinstance(v, str)}
            if others & region:
                return place
    return None


@mcp.tool()
def get_weather(city: str, days: int = 1) -> dict:
    """Get current weather and a daily forecast for a city.
    Use when the user asks about weather, temperature, rain, or whether
    to bring a jacket or umbrella. `city` is a plain city name like
    'Sigmaringen' or 'Berlin'. `days` is 1-7 (1 = today only)."""
    days = max(1, min(days, 7))

    # 1. City name -> coordinates
    place = find_place(city)
    if place is None:
        return {"error": f"City not found: {city}"}

    # 2. Coordinates -> forecast
    data = httpx.get(
        FORECAST_URL,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "forecast_days": days,
            "timezone": "auto",
        },
        timeout=10,
    ).json()

    current = data["current"]
    daily = data["daily"]

    return {
        "city": place["name"],
        "country": place.get("country"),
        "current": {
            "temp_c": current["temperature_2m"],
            "wind_kmh": current["wind_speed_10m"],
            "conditions": WEATHER_CODES.get(current["weather_code"], "unknown"),
        },
        "forecast": [
            {
                "date": daily["time"][i],
                "high_c": daily["temperature_2m_max"][i],
                "low_c": daily["temperature_2m_min"][i],
                "rain_chance_pct": daily["precipitation_probability_max"][i],
                "conditions": WEATHER_CODES.get(daily["weather_code"][i], "unknown"),
            }
            for i in range(len(daily["time"]))
        ],
    }


if __name__ == "__main__":
    mcp.run()
