# Home Assistant Integration

OkoNebo exposes two Home Assistant–friendly endpoints that return data in the shapes HA expects for a custom REST sensor and a weather entity. They always return `200 OK` with availability flags, so HA automations stay stable even when data is temporarily unavailable.

---

## Sensor Entity (`/api/ha/sensor`)

Maps OkoNebo data to a **custom REST sensor** in Home Assistant.

### HA configuration

In `configuration.yaml` (or a split config file):

```yaml
sensor:
  - platform: rest
    name: OkoNebo Weather
    resource: http://192.168.1.x:8888/api/ha/sensor
    # If auth is enabled, add:
    # headers:
    #   Authorization: Bearer YOUR_AGENT_TOKEN
    value_template: "{{ value_json.state }}"
    json_attributes:
      - temperature
      - humidity
      - pressure
      - wind_speed
      - wind_bearing
      - condition
      - threat_level
      - alerts_count
      - max_alert_severity
      - alerts
      - attributes
    scan_interval: 300
```

### Response shape

```json
{
  "state": "default",
  "available": true,
  "threat_level": "default",
  "alerts_count": 0,
  "max_alert_severity": null,
  "location": { "label": "Home", "lat": 36.15, "lon": -95.99, "timezone": "America/Chicago" },
  "temperature": 72.3,
  "humidity": 55,
  "pressure": 29.92,
  "wind_speed": 8.0,
  "wind_bearing": 270,
  "condition": "sunny",
  "alerts": [],
  "attributes": {
    "source": "nws",
    "station": "KBKD",
    "feels_like_f": 74.1,
    "dewpoint_f": 54.0,
    "aqi": 1,
    "aqi_available": true,
    "sunrise": "2026-04-05T06:42:00-05:00",
    "sunset": "2026-04-05T19:58:00-05:00",
    "moon_phase": "waxing_gibbous",
    "error": null
  }
}
```

The `state` field is one of `"default"`, `"approaching"`, or `"active"` — the weather threat level based on active NWS alerts.

### Condition values

The `condition` field uses HA's [weather condition strings](https://www.home-assistant.io/integrations/weather/#condition-mapping):

`clear-night` · `cloudy` · `fog` · `hail` · `lightning` · `lightning-rainy` · `partlycloudy` · `pouring` · `rainy` · `snowy` · `snowy-rainy` · `sunny` · `windy` · `windy-variant` · `exceptional`

### Wind bearing

`wind_bearing` is a numeric compass bearing (0–360, degrees from north). `null` if unavailable.

---

## Weather Entity (`/api/ha/weather`)

Maps OkoNebo data to a **HA weather platform** via REST.

### HA configuration (template weather entity)

The easiest path is a [template weather](https://www.home-assistant.io/integrations/weather.template/) entity fed from a REST sensor. First add a REST sensor for the raw payload:

```yaml
sensor:
  - platform: rest
    name: OkoNebo Weather Entity Raw
    resource: http://192.168.1.x:8888/api/ha/weather
    json_attributes:
      - temperature
      - humidity
      - pressure
      - wind_speed
      - wind_bearing
      - condition
      - forecast
      - available
    value_template: "{{ value_json.condition }}"
    scan_interval: 900
```

Then wire it into a `weather.template`:

```yaml
weather:
  - platform: template
    name: OkoNebo
    condition_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'condition') }}"
    temperature_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'temperature') }}"
    humidity_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'humidity') }}"
    pressure_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'pressure') }}"
    wind_speed_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'wind_speed') }}"
    wind_bearing_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'wind_bearing') }}"
    forecast_template: "{{ state_attr('sensor.okonebo_weather_entity_raw', 'forecast') }}"
```

### Response shape

```json
{
  "available": true,
  "temperature": 72.3,
  "humidity": 55,
  "pressure": 29.92,
  "wind_speed": 8.0,
  "wind_bearing": 270,
  "condition": "sunny",
  "forecast": [
    {
      "datetime": "2026-04-05T18:00:00",
      "condition": "partlycloudy",
      "temperature": 74,
      "templow": null,
      "precipitation_probability": 15
    }
  ],
  "attribution": "Data provided by OkoNebo",
  "error": null
}
```

---

## Authentication

If `AUTH_ENABLED=true`, create an agent token with `weather.read` scope and add it as a header:

```yaml
headers:
  Authorization: Bearer YOUR_AGENT_TOKEN
```

See [agents.md](agents.md) for token creation.

---

## Availability flag

Both endpoints set `"available": false` with an `"error"` field if the underlying data fetch fails. This prevents HA from transitioning to `unavailable` state during brief provider outages — the last good value is still rendered.

---

## Automations using threat level

```yaml
automation:
  - alias: Severe weather alert
    trigger:
      - platform: state
        entity_id: sensor.okonebo_weather
        attribute: threat_level
        to: "active"
    action:
      - service: notify.notify
        data:
          message: "Severe weather alert active!"
```
