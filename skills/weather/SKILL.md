---
name: weather
description: Get weather information for any location via wttr.in.
---

# Weather Skill

Get weather information using the wttr.in service (no API key needed).

## Usage

Use the `web_fetch` tool to get weather data:

### Current Weather
```
web_fetch url="https://wttr.in/London?format=3"
```
Returns: `London: +12°C`

### Detailed Forecast
```
web_fetch url="https://wttr.in/London?format=j1"
```
Returns JSON with detailed forecast data including:
- Current conditions (temperature, humidity, wind)
- 3-day forecast
- Hourly breakdown

### Simple One-Line Format
```
web_fetch url="https://wttr.in/London?format=%l:+%t+%C+%w+%h"
```
Returns: `London: +12°C Partly cloudy ↗15km/h 65%`

## Format Options
- `%t` - Temperature
- `%C` - Weather condition
- `%w` - Wind
- `%h` - Humidity
- `%p` - Precipitation
- `%l` - Location

## Tips
- URL-encode city names with spaces: `New+York` or `New%20York`
- Add `?m` for metric, `?u` for USCS units
- Use `~` prefix for location by name: `~Eiffel+Tower`
