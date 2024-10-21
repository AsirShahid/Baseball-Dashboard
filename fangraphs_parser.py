#!/usr/bin/env python3
import pandas as pd
import requests
from bs4 import BeautifulSoup
import logging
import json
from time import sleep

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def get_fangraphs_data(url, table_id):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', {'id': table_id})
        if not table:
            raise ValueError(f"Table with id {table_id} not found")
        df = pd.read_html(str(table))[0]
        df.drop(df.index[-1], axis=0, inplace=True)
        return df
    except requests.RequestException as e:
        logging.error(f"Error fetching data from {url}: {str(e)}")
        return None
    except ValueError as e:
        logging.error(str(e))
        return None

def process_dataframe(df):
    columns = df.columns.tolist()
    new_columns = [stat for _, stat in columns]
    df.columns = new_columns
    df.drop(df.columns[0], axis=1, inplace=True)
    return df

def main():
    config = load_config()
    year = config['current_year']
    
    urls = {
        'batting': f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=y&type=8&season={year}&month=0&season1={year}&ind=0&team=&rost=&age=&filter=&players=&page=1_10000",
        'pitching': f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=y&type=8&season={year}&month=0&season1={year}&ind=0&team=0&rost=0&age=0&filter=&players=0&startdate=&enddate=&page=1_10000",
        'batting_team': f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=bat&lg=all&qual=0&type=8&season={year}&month=0&season1={year}&ind=0&team=0,ts&rost=&age=&filter=&players=0&startdate=&enddate=",
        'pitching_team': f"https://www.fangraphs.com/leaders.aspx?pos=all&stats=pit&lg=all&qual=0&type=8&season={year}&month=0&season1={year}&ind=0&team=0,ts&rost=0&age=0&filter=&players=0&startdate=&enddate="
    }

    table_id = 'LeaderBoard1_dg1_ctl00'

    for key, url in urls.items():
        logging.info(f"Fetching {key} data...")
        df = get_fangraphs_data(url, table_id)
        if df is not None:
            df = process_dataframe(df)
            df.to_csv(f'{key}_df.csv', index=False)
            logging.info(f"Successfully saved {key}_df.csv")
        sleep(config['request_delay'])  # Rate limiting

if __name__ == "__main__":
    main()
