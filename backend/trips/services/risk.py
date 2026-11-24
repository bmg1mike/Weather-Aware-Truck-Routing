"""Risk thresholds and ``classify`` (spec 6.3). Pure: no I/O, no Django.

Plan phase 2 adds the threshold table and
``classify(wind_mph, rain_in_hr, snow_in_hr, load_lb) -> (RiskLevel, Driver)``.
"""
