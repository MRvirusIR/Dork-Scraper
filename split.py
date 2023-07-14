from colorama import Fore


banner = ''' 
 ____               ____          _ _____ 
| __ ) _   _  __ _ / ___|___   __| |___ / 
|  _ \| | | |/ _` | |   / _ \ / _` | |_ \ 
| |_) | |_| | (_| | |__| (_) | (_| |___) |
|____/ \__,_|\__, |\____\___/ \__,_|____/ 
             |___/  Split Version: 1.0
'''

print(Fore.RED + banner)

input_file = input(Fore.CYAN + "Enter the name of the input TXT file: ")

output_file = 'new_' + input_file
try:
    with open(input_file, 'r') as f1, open(output_file, 'w') as f2:
        for line in f1:
            stripped_line = line.split(' ')[0] + '\n'
            f2.write(stripped_line)
    print(Fore.GREEN + f"[+] Successfully removed spaces from '{input_file}' content.")
    print(Fore.GREEN + f"[+] New content saved in file '{output_file}'.")
except FileNotFoundError:
    print(Fore.GREEN + f"[+] File '{input_file}' not found.")
    exit()
except Exception as e:
    print(Fore.RED + f"[-] An error occurred while processing the file: {e}")
    exit()
