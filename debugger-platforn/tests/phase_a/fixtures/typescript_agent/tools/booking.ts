import * as db from '../database';

/** Book a new appointment for the customer */
export async function bookAppointment(
    date: string,
    time: string,
    customerName: string,
    notes: string = ""
): Promise<AppointmentResult> {
    if (!date) {
        throw new Error("date is required");
    }
    if (!customerName) {
        throw new Error("customerName is required");
    }

    await db.execute("INSERT INTO appointments (date, time, name, notes) VALUES (?, ?, ?, ?)",
        date, time, customerName, notes);
    await db.commit();

    return { id: "APT-001", status: "confirmed" };
}

interface AppointmentResult {
    id: string;
    status: string;
}
