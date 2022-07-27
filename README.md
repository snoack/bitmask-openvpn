This script generates and updates the OpenVPN config for [Bitmask/Riseup VPN][bitmask-vpn],
so that the VPN can be used without the GUI client.

**Please consider [donating to Riseup][donate] for using their VPN!**

## Usage

The script requires the CA certificate to be stored in the current working
directory as `ca.pem`, and will write `bitmask.ovpn` and `cert.pem` on
successful completion to the current working directory:

```sh
# Create directory
mkdir riseup-vpn
cd riseup-vpn

# Download CA certificate
wget https://raw.githubusercontent.com/leapcode/bitmask-vpn/main/providers/riseup/riseup-ca.crt -O ca.pem

# Generate or update configuration and user certificate
/path/to/bitmask-openvpn.py

# Start OpenVPN
openvpn --config bitmask.ovpn
```

If the contents of the generated files changed, it restarts OpenVPN if running.
It's recommended to run `bitmask-openvpn.py` daily (e.g. through a cronjob) but
make sure to run it from the same directory that has the previously generated files.

## Configuration

By default the script, uses Riseup's VPN gateways located in the US. In order to
use a different Bitmask VPN provider, change the variable `API_URL` in the script,
and download the respective CA certificate instead. In order to use gateways from
a different region, change the variable `COUNTRY_CODES` in the script.

Note: Only *anon* authentification, and gateways of the type *openvpn* are supported.

## Setup with split-vpn on Unifi gateway

This tutorial will configure a VLAN that routes all traffic through RiseupVPN
on the UDM, UDM Pro, UDM-SE, UDR, or UXG.

1. Follow instructions to install [split-vpn].
    * Recommended: Set up split-vpn to run at boot. Otherwise, traffic will not
      go through the VPN after the gateway boots up again.
2. Log into your Unifi gateway and create a new network:
    1. Network app -> Settings (gear icon) -> Networks -> Create New Network
    2. Disable *Auto Scale Network*
    3. Advanced Configuration -> DHCP Service Management -> DHCP DNS Server
        * Enable and set to 10.41.0.1 (this is the DNS server set by the official Bitmask client)
3. SSH into the Unifi Gateway and create a directory with the OpenVPN configuration files:
    ```sh
    mkdir -p /etc/split-vpn/openvpn/riseup
    cd /etc/split-vpn/openvpn/riseup
    cp /etc/split-vpn/vpn/vpn.conf.sample vpn.conf
    wget https://raw.githubusercontent.com/leapcode/bitmask-vpn/main/providers/riseup/riseup-ca.crt -O ca.pem
    wget https://raw.githubusercontent.com/snoack/bitmask-openvpn/main/bitmask-openvpn.py
    chmod +x bitmask-openvpn.py
    ```
4. Edit `vpn.conf`
    * Set `FORCED_SOURCE_IPV4` matching the *Host Address* and
      *Netmask* set in step 2 (e.g. if *Host Address* is 192.168.5.1
      and *Netmask* is 24, set `FORCED_SOURCE_IPV4="192.168.5.0/24"`).
    * Make sure that `ROUTE_TABLE`, `MARK`, `PREFIX`, `PREF`, and `DEV`
      are unique from other VPNs configured.
    * Set `KILLSWITCH=1` and `REMOVE_KILLSWITCH_ON_EXIT=0`. This prevents
      traffic from being leaked past the VPN if OpenVPN stops running.
    * Add follwing hook to the bottom of the file:
        ```sh
        hooks_pre_up() {
            local script="/etc/cron.daily/bitmask-openvpn-$(basename $PWD)"
            if [ ! -f $script ]; then
              printf '#!/bin/sh\ncd %s\n./bitmask-openvpn.py' $PWD > $script
              chmod +x $script
            fi
            ./bitmask-openvpn.py
        }
        ```
5. Create `run-vpn.sh` wih following contents:
    ```sh
    #!/bin/sh                                                                                            
    cd $(dirname "$0")                                                                                   
    . ./vpn.conf                                                                                         
    /etc/split-vpn/vpn/updown.sh ${DEV} pre-up >pre-up.log 2>&1                                          
    nohup openvpn --config bitmask.ovpn \                                                                
                  --route-noexec --redirect-gateway def1 \                                               
                  --up /etc/split-vpn/vpn/updown.sh \                                                    
                  --down /etc/split-vpn/vpn/updown.sh \                                                  
                  --dev-type tun --dev ${DEV} \                                                          
                  --script-security 2 \                                                                  
                  --mute-replay-warnings >openvpn.log 2>&1 &
    ```
6. Give the run script executable permissions and run it once:
    ```sh
    chmod +x run-vpn.sh
    ./run-vpn.sh
    ```
7. If split-vpn was set up to run at boot, edit `/etc/split-vpn/run-vpn.sh`
   and add `/etc/split-vpn/openvpn/riseup/run-vpn.sh` on a new line.

[bitmask-vpn]: https://github.com/leapcode/bitmask-vpn
[donate]: https://riseup.net/en/donate
[split-vpn]: https://github.com/peacey/split-vpn
