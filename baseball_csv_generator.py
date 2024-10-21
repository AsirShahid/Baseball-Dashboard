#!/usr/bin/env python3

import pybaseball as pyb
from pybaseball import team_batting, team_pitching, team_fielding, batting_stats, pitching_stats
import pandas as pd
from pathlib import Path
from time import sleep
import datetime
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Disable pybaseball cache
pyb.cache.disable()

# Load configuration
def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

# Create directories if they don't exist
def create_directories(directories):
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

# Generate CSV for a specific statistic
def generate_csv(func, year, directory, qual=None):
    try:
        if qual is not None:
            df = func(year, qual=qual)
        else:
            df = func(year)
        df.to_csv(Path(directory) / f"{year}.csv")
        logging.info(f"Generated CSV for {func.__name__} - {year}")
    except Exception as e:
        logging.error(f"Error generating CSV for {func.__name__} - {year}: {str(e)}")

# Main function to generate all CSVs
def generate_all_csvs(start_year, end_year, config):
    for year in range(end_year, start_year - 1, -1):
        generate_csv(team_batting, year, config['team_batting_dir'])
        generate_csv(team_pitching, year, config['team_pitching_dir'])
        generate_csv(team_fielding, year, config['team_fielding_dir'])
        generate_csv(batting_stats, year, config['qualified_batting_dir'])
        generate_csv(pitching_stats, year, config['qualified_pitching_dir'])
        generate_csv(batting_stats, year, config['all_batting_dir'], qual=0)
        generate_csv(pitching_stats, year, config['all_pitching_dir'], qual=0)

# Main execution
if __name__ == "__main__":
    config = load_config()
    
    create_directories([
        config['team_batting_dir'],
        config['team_pitching_dir'],
        config['team_fielding_dir'],
        config['qualified_batting_dir'],
        config['qualified_pitching_dir'],
        config['all_batting_dir'],
        config['all_pitching_dir']
    ])

    current_year = datetime.datetime.now().year
    
    # Generate historical data
    generate_all_csvs(config['start_year'], current_year, config)

    # Continuous update loop
    while True:
        generate_all_csvs(current_year, current_year, config)
        logging.info(f"Sleeping for {config['update_interval']} seconds")
        sleep(config['update_interval'])
