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
   git clone https://github.com/your-username/Baseball-Dashboard.git
   cd Baseball-Dashboard
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Update the data (optional):
   ```
   python baseball_csv_generator.py
   python fangraphs_parser.py
   ```

4. Run the Streamlit dashboard:
   ```
   streamlit run streamlit-dashboard.py
   ```

5. Open your web browser and navigate to the URL provided by Streamlit (usually http://localhost:8501)

## Configuration

You can modify the `config.json` file to update settings such as the current year, data directories, and update intervals.

## Data Sources

The data is provided by [Fangraphs](https://www.fangraphs.com/) and processed using [pybaseball](https://pypi.org/project/pybaseball/). The plots are generated using [matplotlib](https://matplotlib.org/) and [plotly](https://plotly.com/python/).

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the [MIT License](LICENSE).
