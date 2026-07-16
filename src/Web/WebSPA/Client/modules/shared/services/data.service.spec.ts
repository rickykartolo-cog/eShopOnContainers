import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { DataService } from './data.service';
import { SecurityService } from './security.service';

describe('DataService', () => {
    let service: DataService;
    let httpMock: HttpTestingController;
    const securityServiceStub = {
        GetToken: () => 'test-token'
    } as SecurityService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                DataService,
                { provide: SecurityService, useValue: securityServiceStub },
                provideHttpClient(),
                provideHttpClientTesting()
            ]
        });
        service = TestBed.inject(DataService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('issues GET requests with a bearer token', () => {
        let response: any;
        service.get('/api/v1/catalog/items').subscribe(res => response = res);

        const req = httpMock.expectOne('/api/v1/catalog/items');
        expect(req.request.method).toBe('GET');
        expect(req.request.headers.get('authorization')).toBe('Bearer test-token');
        req.flush({ data: [] });
        expect(response).toEqual({ data: [] });
    });

    it('adds an x-requestid header for idempotent POSTs', () => {
        service.postWithId('/api/v1/basket/checkout', { id: 1 }).subscribe();

        const req = httpMock.expectOne('/api/v1/basket/checkout');
        expect(req.request.method).toBe('POST');
        expect(req.request.headers.get('x-requestid')).toBeTruthy();
        expect(req.request.headers.get('authorization')).toBe('Bearer test-token');
        req.flush({});
    });
});
