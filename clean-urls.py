from colorama import Fore


banner = ''' 
 ____               ____          _ _____ 
| __ ) _   _  __ _ / ___|___   __| |___ / 
|  _ \| | | |/ _` | |   / _ \ / _` | |_ \ 
| |_) | |_| | (_| | |__| (_) | (_| |___) |
|____/ \__,_|\__, |\____\___/ \__,_|____/ 
             |___/  Clean-URLS Version: 1.0
'''

print(Fore.RED + banner)

def remove_duplicates(urls, output_file):
    unique_urls = set(urls)
    with open(output_file, 'w') as file:
        file.write('\n'.join(unique_urls))

input_file = input(Fore.CYAN + "Enter the name of the file with URLs: ")
output_file = 'list.txt'

urls = []
with open(input_file) as file:
    for line in file:
        url = line.strip()
        if not url.endswith('/'):
            url += '/'
        urls.append(url)

remove_duplicates(urls, output_file)

print(Fore.GREEN + "[+] Modified and unique URLs have been saved to", output_file)

