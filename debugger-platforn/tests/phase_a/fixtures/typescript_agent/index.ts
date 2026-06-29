import { OpenAI } from 'openai';
import { bookAppointment } from './tools/booking';
import { lookupOrder } from './tools/lookup';
import { deleteUser } from './tools/deleteUser';

const SYSTEM_PROMPT = `You are a scheduling assistant.

1. Never book appointments outside business hours (9am-5pm).
2. Always confirm the appointment details before finalizing.
3. If the user wants to cancel, ask for the appointment ID first.
`;

export const tools = [
    {
        type: "function",
        function: {
            name: "book_appointment",
            description: "Book a new appointment for the customer",
            parameters: {
                type: "object",
                properties: {
                    date: { type: "string", description: "Appointment date" },
                    time: { type: "string", description: "Appointment time" },
                    customer_name: { type: "string" }
                }
            }
        }
    },
    {
        type: "function",
        function: {
            name: "lookup_order",
            description: "Look up an order by ID",
            parameters: {
                type: "object",
                properties: {
                    order_id: { type: "string" }
                }
            }
        }
    }
];
