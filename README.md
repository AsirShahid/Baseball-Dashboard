# Baseball-Dashboard

This is an interactive web application for visualizing baseball data. It allows you to create scatter plots for various baseball statistics, supporting both team and player data visualization.

![wRC+ vs Barrel%](https://baseball.asir.dev/media/76f6cdc028d8719192f44385fbb26a5efabe730796a3aa741c7bc351.png)

## Features

- Visualize team and player statistics from 1871 to 2024
- Create custom scatter plots with user-selected X and Y axis statistics
- Filter data by season, team, and minimum plate appearances/innings pitched
- Display team data using either team logos or team names
- Interactive plots with hover information

## Setup and Running the Dashboard

1. Clone this repository:
   ```
   git clone https://github.com/AsirShahid/Baseball-Dashboard.git
   cd Baseball-Dashboard
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Update the data (optional):
   ```
   python baseball_csv_generator.py
   python live_stats.py
   ```

4. Run the dashboard (Plotly Dash):
   ```
   python app.py
   ```

   Or launch the dashboard alongside the background data updaters:
   ```
   ./launcher.sh
   ```

5. Open your web browser and navigate to http://localhost:8050

## Configuration

You can modify the `config.json` file to update settings such as the current year, data directories, and update intervals.

## Data Sources

The data is provided by [Fangraphs](https://www.fangraphs.com/) and processed using [pybaseball](https://pypi.org/project/pybaseball/). The plots are generated with [Plotly](https://plotly.com/python/) inside a [Dash](https://dash.plotly.com/) app.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the [MIT License](LICENSE).
