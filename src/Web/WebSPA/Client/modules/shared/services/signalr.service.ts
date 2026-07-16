import { Injectable } from '@angular/core';
import { SecurityService } from './security.service';
import { ConfigurationService } from './configuration.service';
import { io, Socket } from 'socket.io-client';
import { ToastrService } from 'ngx-toastr';
import { Subject } from 'rxjs';

// Realtime order-status notifications. The hub is now a Socket.IO server
// (python ordering-signalrhub) served at the same /hub/notificationhub path,
// authenticated with the access token in the connection query string, and it
// emits the same 'UpdatedOrderState' message with { orderId, status }.
@Injectable()
export class SignalrService {
    private socket: Socket;
    private SignalrHubUrl: string = '';
    private msgSignalrSource = new Subject<void>();
    msgReceived$ = this.msgSignalrSource.asObservable();

    constructor(
        private securityService: SecurityService,
        private configurationService: ConfigurationService, private toastr: ToastrService,
    ) {
        if (this.configurationService.isReady) {
            this.SignalrHubUrl = this.configurationService.serverSettings.signalrHubUrl;
            this.init();
        }
        else {
            this.configurationService.settingsLoaded$.subscribe(x => {
                this.SignalrHubUrl = this.configurationService.serverSettings.signalrHubUrl;
                this.init();
            });
        }
    }

    public stop() {
        if (this.socket) {
            this.socket.disconnect();
        }
    }

    private init() {
        if (this.securityService.IsAuthorized == true) {
            this.register();
            this.registerHandlers();
        }
    }

    private register() {
        this.socket = io(this.SignalrHubUrl, {
            path: '/hub/notificationhub',
            query: { access_token: this.securityService.GetToken() },
            transports: ['websocket', 'polling'],
            reconnection: true
        });
        this.socket.on('connect', () => {
            console.log('Hub connection started');
        });
        this.socket.on('connect_error', () => {
            console.log('Error while establishing connection');
        });
    }

    private registerHandlers() {
        this.socket.on('UpdatedOrderState', (msg) => {
            console.log(`Order ${msg.orderId} updated to ${msg.status}`);
            this.toastr.success('Updated to status: ' + msg.status, 'Order Id: ' + msg.orderId);
            this.msgSignalrSource.next();
        });
    }
}
