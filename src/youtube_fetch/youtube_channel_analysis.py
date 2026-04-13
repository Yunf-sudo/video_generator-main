from youtube_fetcher import fetch_channel_info

def analysis_channel(channel_identifier: str, output_dir: str):
    output_file = fetch_channel_info(channel_identifier, output_dir)
    