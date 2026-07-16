import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { ToastrService } from 'ngx-toastr';

import { SignalrService } from './signalr.service';
import { SecurityService } from './security.service';
import { ConfigurationService } from './configuration.service';

const mockSocket = {
    handlers: {} as Record<string, (msg?: any) => void>,
    on(event: string, handler: (msg?: any) => void) {
        this.handlers[event] = handler;
    },
    disconnect: jest.fn()
};

jest.mock('socket.io-client', () => ({
    io: jest.fn(() => mockSocket)
}));

import { io } from 'socket.io-client';

describe('SignalrService', () => {
    let toastrStub: { success: jest.Mock };

    beforeEach(() => {
        mockSocket.handlers = {};
        mockSocket.disconnect.mockClear();
        (io as jest.Mock).mockClear();
        toastrStub = { success: jest.fn() };

        TestBed.configureTestingModule({
            providers: [
                SignalrService,
                { provide: SecurityService, useValue: { IsAuthorized: true, GetToken: () => 'test-token' } },
                {
                    provide: ConfigurationService,
                    useValue: {
                        isReady: true,
                        settingsLoaded$: new Subject<void>().asObservable(),
                        serverSettings: { signalrHubUrl: 'http://localhost:5202' }
                    }
                },
                { provide: ToastrService, useValue: toastrStub }
            ]
        });
    });

    it('connects to the frozen /hub/notificationhub path with the access token in the query string', () => {
        TestBed.inject(SignalrService);

        expect(io).toHaveBeenCalledWith('http://localhost:5202', expect.objectContaining({
            path: '/hub/notificationhub',
            query: { access_token: 'test-token' }
        }));
    });

    it('surfaces UpdatedOrderState messages with the same user-visible semantics', () => {
        const service = TestBed.inject(SignalrService);
        let notified = false;
        service.msgReceived$.subscribe(() => notified = true);

        mockSocket.handlers['UpdatedOrderState']({ orderId: 42, status: 'shipped' });

        expect(toastrStub.success).toHaveBeenCalledWith('Updated to status: shipped', 'Order Id: 42');
        expect(notified).toBe(true);
    });

    it('disconnects on stop()', () => {
        const service = TestBed.inject(SignalrService);
        service.stop();
        expect(mockSocket.disconnect).toHaveBeenCalled();
    });
});
