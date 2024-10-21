#!/usr/bin/env python3

import dash
from dash import dcc
from dash import html
from dash.dependencies import Input, Output
import plotly.express as px
import pandas as pd
import os
import glob

# Load team batting data from multiple CSV files
team_batting_files = glob.glob('team_batting/*.csv')
team_batting_list = []

for file in team_batting_files:
    df = pd.read_csv(file)
    team_batting_list.append(df)

if len(team_batting_list) > 0:
    team_batting = pd.concat(team_batting_list, ignore_index=True)
else:
    team_batting = pd.DataFrame()

# Load team pitching data from multiple CSV files
team_pitching_files = glob.glob('team_pitching/*.csv')
team_pitching_list = []

for file in team_pitching_files:
    df = pd.read_csv(file)
    team_pitching_list.append(df)

if len(team_pitching_list) > 0:
    team_pitching = pd.concat(team_pitching_list, ignore_index=True)
else:
    team_pitching = pd.DataFrame()

# Load player batting data from multiple CSV files
player_batting_files = glob.glob('player_batting/*.csv')
player_batting_list = []

for file in player_batting_files:
    df = pd.read_csv(file)
    player_batting_list.append(df)

if len(player_batting_list) > 0:
    player_batting = pd.concat(player_batting_list, ignore_index=True)
else:
    player_batting = pd.DataFrame()

# Load player pitching data from multiple CSV files
player_pitching_files = glob.glob('player_pitching/*.csv')
player_pitching_list = []

for file in player_pitching_files:
    df = pd.read_csv(file)
    player_pitching_list.append(df)

if len(player_pitching_list) > 0:
    player_pitching = pd.concat(player_pitching_list, ignore_index=True)
else:
    player_pitching = pd.DataFrame()

# Preprocess data (replace with your own data preprocessing logic)
if not team_batting.empty and 'Season' in team_batting.columns:
    team_batting['Season'] = pd.to_datetime(team_batting['Season'], format='%Y').dt.strftime('%Y')
if not team_pitching.empty and 'Season' in team_pitching.columns:
    team_pitching['Season'] = pd.to_datetime(team_pitching['Season'], format='%Y').dt.strftime('%Y')
if not player_batting.empty and 'Season' in player_batting.columns:
    player_batting['Season'] = pd.to_datetime(player_batting['Season'], format='%Y').dt.strftime('%Y')
if not player_pitching.empty and 'Season' in player_pitching.columns:
    player_pitching['Season'] = pd.to_datetime(player_pitching['Season'], format='%Y').dt.strftime('%Y')

# Create the Dash app
app = dash.Dash(__name__, suppress_callback_exceptions=True)

# Define the layout
app.layout = html.Div([
    html.H1('Baseball Statistics Dashboard', style={'textAlign': 'center'}),
    dcc.Tabs(id='tabs', value='team', children=[
        dcc.Tab(label='Team Stats', value='team'),
        dcc.Tab(label='Player Stats', value='player')
    ]),
    html.Div(id='tab-content')
])

# Define the callback for rendering tab content
@app.callback(Output('tab-content', 'children'),
              [Input('tabs', 'value')])
def render_tab_content(tab):
    if tab == 'team':
        return html.Div([
            html.H2('Team Statistics'),
            dcc.Dropdown(
                id='team-season-dropdown',
                options=[{'label': season, 'value': season} for season in sorted(team_batting['Season'].unique(), reverse=True)] if 'Season' in team_batting.columns else [],
                value=team_batting['Season'].max() if not team_batting.empty and 'Season' in team_batting.columns else None,
                clearable=False
            ),
            dcc.RadioItems(
                id='team-stat-type',
                options=[
                    {'label': 'Batting', 'value': 'batting'},
                    {'label': 'Pitching', 'value': 'pitching'}
                ],
                value='batting',
                labelStyle={'display': 'inline-block', 'marginRight': '10px'}
            ),
            dcc.Dropdown(
                id='team-x-axis-dropdown',
                options=[],
                value=None,
                clearable=False
            ),
            dcc.Dropdown(
                id='team-y-axis-dropdown',
                options=[],
                value=None,
                clearable=False
            ),
            dcc.RadioItems(
                id='team-label-option',
                options=[
                    {'label': 'Team Name', 'value': 'name'},
                    {'label': 'Team Logo', 'value': 'logo'}
                ],
                value='name',
                labelStyle={'display': 'inline-block', 'marginRight': '10px'}
            ),
            dcc.Graph(id='team-graph')
        ])
    elif tab == 'player':
        return html.Div([
            html.H2('Player Statistics'),
            dcc.Dropdown(
                id='player-season-dropdown',
                options=[{'label': season, 'value': season} for season in player_batting['Season'].unique()] if 'Season' in player_batting.columns else [],
                value=player_batting['Season'].max() if not player_batting.empty and 'Season' in player_batting.columns else None,
                clearable=False
            ),
            dcc.Dropdown(
                id='player-stat-dropdown',
                options=[],
                value=None,
                clearable=False
            ),
            dcc.Graph(id='player-graph')
        ])
        
# Define the callback for updating team dropdown options based on the selected stat type
@app.callback(
    [Output('team-x-axis-dropdown', 'options'),
     Output('team-x-axis-dropdown', 'value'),
     Output('team-y-axis-dropdown', 'options'),
     Output('team-y-axis-dropdown', 'value')],
    [Input('tabs', 'value'),
     Input('team-season-dropdown', 'value'),
     Input('team-stat-type', 'value')])
def update_team_dropdowns(tab, season, stat_type):
    if tab == 'team' and season is not None:
        if stat_type == 'batting':
            df = team_batting[team_batting['Season'] == season]
            cols = [{'label': col, 'value': col} for col in df.columns if col != 'Season']
        else:
            df = team_pitching[team_pitching['Season'] == season]
            cols = [{'label': col, 'value': col} for col in df.columns if col != 'Season']
        return cols, cols[1]['value'] if len(cols) > 1 else None, cols, cols[-1]['value'] if len(cols) > 1 else None
    return [], None, [], None

# Define the callback for updating the player stat dropdown options
@app.callback(Output('player-stat-dropdown', 'options'),
              [Input('player-season-dropdown', 'value')])
def update_player_stat_dropdown(season):
    if season is not None:
        if season in player_batting['Season'].unique():
            df = player_batting[player_batting['Season'] == season]
            return [{'label': col, 'value': col} for col in df.columns if col != 'Season']
        else:
            df = player_pitching[player_pitching['Season'] == season]
            return [{'label': col, 'value': col} for col in df.columns if col != 'Season']
    return []

# Define the callback for updating the team graph
@app.callback(Output('team-graph', 'figure'),
              [Input('team-season-dropdown', 'value'),
               Input('team-x-axis-dropdown', 'value'),
               Input('team-y-axis-dropdown', 'value'),
               Input('team-label-option', 'value'),
               Input('team-stat-type', 'value')])
def update_team_graph(season, x_axis, y_axis, label_option, stat_type):
    if season is not None and x_axis is not None and y_axis is not None:
        if stat_type == 'batting':
            df = team_batting[team_batting['Season'] == season]
        else:
            df = team_pitching[team_pitching['Season'] == season]
        
        if label_option == 'name':
            text = df['Team']
            marker_size = 0
        else:
            text = None
            marker_size = 10
        
        fig = px.scatter(df, x=x_axis, y=y_axis, text=text,
                        title=f'Team {y_axis} vs {x_axis} for Season {season}')
        fig.update_traces(marker_size=marker_size)
        fig.update_layout(xaxis_title=x_axis, yaxis_title=y_axis)
        return fig
    else:
        return {}

# Define the callback for updating the player graph  
@app.callback(Output('player-graph', 'figure'),
              [Input('player-season-dropdown', 'value'),
               Input('player-stat-dropdown', 'value')])
def update_player_graph(season, stat):
    if season is not None and stat is not None:
        if season in player_batting['Season'].unique():
            df = player_batting[player_batting['Season'] == season]
        else:
            df = player_pitching[player_pitching['Season'] == season]
        
        if stat in df.columns:
            fig = px.scatter(df, x='Name', y=stat, title=f'Player {stat} for Season {season}')
            fig.update_layout(xaxis_title='Player', yaxis_title=stat)
            return fig
        else:
            return {}
    else:
        return {}

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)