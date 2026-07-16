using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using Microsoft.eShopOnContainers.BuildingBlocks.EventBus.Events;
using Newtonsoft.Json;

using CatalogEvents = Microsoft.eShopOnContainers.Services.Catalog.API.IntegrationEvents.Events;
using BasketEvents = Basket.API.IntegrationEvents.Events;
using BasketModel = Microsoft.eShopOnContainers.Services.Basket.API.Model;
using OrderingEvents = Ordering.API.Application.IntegrationEvents.Events;
using BackgroundEvents = Ordering.BackgroundTasks.Events;
using PaymentEvents = Payment.API.IntegrationEvents.Events;
using LocationEvents = Microsoft.eShopOnContainers.Services.Locations.API.IntegrationEvents.Events;
using LocationModel = Microsoft.eShopOnContainers.Services.Locations.API.Model;

namespace EventContractsGenerator
{
    /// <summary>
    /// Emits golden Newtonsoft.Json examples for every integration event in the
    /// producer/consumer matrix, serialized exactly as EventBusRabbitMQ publishes them
    /// (JsonConvert.SerializeObject with default settings).
    /// Id/CreationDate are pinned to deterministic values so goldens are reproducible.
    /// </summary>
    public static class Program
    {
        private static readonly Guid FixedId = Guid.Parse("11111111-2222-3333-4444-555555555555");
        private static readonly DateTime FixedCreationDate =
            new DateTime(2020, 1, 2, 3, 4, 5, 678, DateTimeKind.Utc);
        private static readonly Guid FixedRequestId = Guid.Parse("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");

        public static int Main(string[] args)
        {
            var outDir = args.Length > 0 ? args[0] : "contracts/events";
            Directory.CreateDirectory(outDir);

            var basket = new BasketModel.CustomerBasket("alice@eshop")
            {
                Items = new List<BasketModel.BasketItem>
                {
                    new BasketModel.BasketItem
                    {
                        Id = "basket-item-1",
                        ProductId = 1,
                        ProductName = ".NET Bot Black Hoodie",
                        UnitPrice = 19.50m,
                        OldUnitPrice = 18.00m,
                        Quantity = 2,
                        PictureUrl = "http://externalcatalogbaseurltobereplaced/c/api/v1/catalog/items/1/pic/"
                    }
                }
            };

            var events = new IntegrationEvent[]
            {
                new CatalogEvents.ProductPriceChangedIntegrationEvent(1, 21.50m, 19.50m),
                new CatalogEvents.OrderStockConfirmedIntegrationEvent(42),
                new CatalogEvents.OrderStockRejectedIntegrationEvent(42,
                    new List<CatalogEvents.ConfirmedOrderStockItem>
                    {
                        new CatalogEvents.ConfirmedOrderStockItem(1, false),
                        new CatalogEvents.ConfirmedOrderStockItem(2, true)
                    }),
                new BasketEvents.UserCheckoutAcceptedIntegrationEvent(
                    "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5", "alice@eshop", "Seattle", "123 Main St",
                    "WA", "U.S.", "98101", "4012888888881881", "Alice Smith",
                    new DateTime(2025, 12, 31, 0, 0, 0, DateTimeKind.Utc), "535", 1,
                    "alice@eshop", FixedRequestId, basket),
                new OrderingEvents.OrderStartedIntegrationEvent("e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"),
                new OrderingEvents.OrderStatusChangedToSubmittedIntegrationEvent(42, "submitted", "alice@eshop"),
                new OrderingEvents.OrderStatusChangedToAwaitingValidationIntegrationEvent(42,
                    "awaitingvalidation", "alice@eshop",
                    new List<OrderingEvents.OrderStockItem>
                    {
                        new OrderingEvents.OrderStockItem(1, 2),
                        new OrderingEvents.OrderStockItem(3, 1)
                    }),
                new OrderingEvents.OrderStatusChangedToStockConfirmedIntegrationEvent(42, "stockconfirmed", "alice@eshop"),
                new OrderingEvents.OrderStatusChangedToPaidIntegrationEvent(42, "paid", "alice@eshop",
                    new List<OrderingEvents.OrderStockItem>
                    {
                        new OrderingEvents.OrderStockItem(1, 2),
                        new OrderingEvents.OrderStockItem(3, 1)
                    }),
                new OrderingEvents.OrderStatusChangedToShippedIntegrationEvent(42, "shipped", "alice@eshop"),
                new OrderingEvents.OrderStatusChangedToCancelledIntegrationEvent(42, "cancelled", "alice@eshop"),
                new BackgroundEvents.GracePeriodConfirmedIntegrationEvent(42),
                new PaymentEvents.OrderPaymentSucceededIntegrationEvent(42),
                new PaymentEvents.OrderPaymentFailedIntegrationEvent(42),
                new LocationEvents.UserLocationUpdatedIntegrationEvent(
                    "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
                    new List<LocationModel.UserLocationDetails>
                    {
                        new LocationModel.UserLocationDetails
                        {
                            LocationId = 1,
                            Code = "SEAT",
                            Description = "Seattle"
                        }
                    })
            };

            foreach (var @event in events)
            {
                PinBaseFields(@event);
                var eventName = @event.GetType().Name;
                var json = JsonConvert.SerializeObject(@event);
                File.WriteAllText(Path.Combine(outDir, eventName + ".golden.json"), json);
                Console.WriteLine($"wrote {eventName}.golden.json");
            }

            return 0;
        }

        private static void PinBaseFields(IntegrationEvent @event)
        {
            var type = typeof(IntegrationEvent);
            type.GetProperty("Id", BindingFlags.Public | BindingFlags.Instance)
                .SetValue(@event, FixedId);
            type.GetProperty("CreationDate", BindingFlags.Public | BindingFlags.Instance)
                .SetValue(@event, FixedCreationDate);
        }
    }
}
